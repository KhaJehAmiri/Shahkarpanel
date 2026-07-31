"""
Functions for managing proxy hosts, users, user templates, nodes, and administrative tasks.
"""

from datetime import datetime, timedelta
from enum import Enum
import secrets
import time
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import and_, delete, func, or_
from sqlalchemy.orm import Query, Session, contains_eager, joinedload
from sqlalchemy.sql.functions import coalesce

from app.db.models import (
    JWT,
    TLS,
    Admin,
    AdminUsageLogs,
    ClientProbe,
    ClientTelemetry,
    DedicatedIP,
    NextPlan,
    Node,
    NodeGroup,
    NodeUsage,
    NodeUserUsage,
    NodeUserProtocolUsage,
    NodeSingBox,
    NodeWireGuard,
    NodeServiceBinding,
    NotificationReminder,
    PanelService,
    Plan,
    Proxy,
    ProxyHost,
    ProxyInbound,
    ProxyTypes,
    SubscriptionEndpoint,
    SubscriptionTokenAlias,
    System,
    Tunnel,
    User,
    UserOrder,
    UserTemplate,
    UserUsageResetLogs,
    Invoice,
    PaymentIntent,
    excluded_inbounds_association,
)
from app.models.admin import AdminCreate, AdminModify, AdminPartialModify
from app.models.node import CoreKind, NodeCreate, NodeModify, NodeStatus, NodeUsageResponse
from app.models.proxy import ProxyHost as ProxyHostModify
from app.models.user import (
    ReminderType,
    UserCreate,
    UserDailyUsageDay,
    UserDataLimitResetStrategy,
    UserModify,
    UserResponse,
    UserStatus,
    UserUsageResponse,
)
from app.models.user_template import UserTemplateCreate, UserTemplateModify, NATIVE_TEMPLATE_PROTOCOLS, native_template_marker
from app.utils.helpers import calculate_expiration_days, calculate_usage_percent
from config import NOTIFY_DAYS_LEFT, NOTIFY_REACHED_USAGE_PERCENT, USERS_AUTODELETE_DAYS


def add_default_host(db: Session, inbound: ProxyInbound, *, commit: bool = True):
    """
    Adds a default host to a proxy inbound.

    Args:
        db (Session): Database session.
        inbound (ProxyInbound): Proxy inbound to add the default host to.
    """
    # Native product buckets dial *node* endpoints, not the panel's public IP.
    address = "{NODE_IP}" if str(inbound.tag or "").startswith("__native:") else "{SERVER_IP}"
    host = ProxyHost(
        remark="{REGION_FLAG} {REGION_NAME} · {PROTOCOL}",
        address=address,
        inbound=inbound,
    )
    db.add(host)
    if commit:
        db.commit()
    else:
        db.flush()


def get_or_create_inbound(
    db: Session,
    inbound_tag: str,
    *,
    inbound_cache: Optional[Dict[str, ProxyInbound]] = None,
    commit: bool = True,
) -> ProxyInbound:
    """
    Retrieves or creates a proxy inbound based on the given tag.

    Args:
        db (Session): Database session.
        inbound_tag (str): The tag of the inbound.
        inbound_cache: Optional tag->ProxyInbound lookaside cache shared across
            many calls (e.g. a migration batch importing thousands of users).
            The set of inbounds is effectively static during such a batch, so
            reusing this avoids a ``SELECT`` + session autoflush per lookup —
            on a large uncommitted transaction that autoflush cost grows with
            the session size and was the dominant cost of slow migrations.
        commit: When False, defer the commit to the caller (batch imports
            commit once at the end instead of once per inbound touched).

    Returns:
        ProxyInbound: The retrieved or newly created proxy inbound.
    """
    if inbound_cache is not None:
        cached = inbound_cache.get(inbound_tag)
        if cached is not None:
            return cached
    inbound = db.query(ProxyInbound).filter(ProxyInbound.tag == inbound_tag).first()
    if not inbound:
        inbound = ProxyInbound(tag=inbound_tag)
        db.add(inbound)
        if commit:
            db.commit()
            add_default_host(db, inbound)
            db.refresh(inbound)
        else:
            db.flush()
            add_default_host(db, inbound, commit=False)
    if inbound_cache is not None:
        inbound_cache[inbound_tag] = inbound
    return inbound


def _proxy_host_row(inbound, host: ProxyHostModify) -> ProxyHost:
    from app.models.proxy import ProxyHostSecurity

    try:
        sec = host.security if not isinstance(host.security, str) else ProxyHostSecurity(host.security)
    except ValueError:
        sec = ProxyHostSecurity.inbound_default
    if sec == ProxyHostSecurity.same:
        sec = ProxyHostSecurity.inbound_default
    return ProxyHost(
        remark=host.remark,
        address=host.address,
        port=host.port,
        path=host.path,
        sni=host.sni,
        host=host.host,
        inbound=inbound,
        security=sec,
        alpn=host.alpn,
        fingerprint=host.fingerprint,
        allowinsecure=host.allowinsecure,
        is_disabled=host.is_disabled,
        mux_enable=host.mux_enable,
        fragment_setting=host.fragment_setting,
        noise_setting=host.noise_setting,
        random_user_agent=host.random_user_agent,
        use_sni_as_host=host.use_sni_as_host,
        sort_order=getattr(host, "sort_order", 0) or 0,
        override_sni_from_address=getattr(host, "override_sni_from_address", False) or False,
        keep_sni_blank=getattr(host, "keep_sni_blank", False) or False,
        pinned_peer_cert_sha256=getattr(host, "pinned_peer_cert_sha256", None),
        verify_peer_cert_by_name=getattr(host, "verify_peer_cert_by_name", None),
        ech_config_list=getattr(host, "ech_config_list", None),
        mux_params=getattr(host, "mux_params", None),
        sockopt_params=getattr(host, "sockopt_params", None),
        final_mask=getattr(host, "final_mask", None),
        vless_route=getattr(host, "vless_route", None),
        exclude_from_sub_types=getattr(host, "exclude_from_sub_types", None),
        mihomo_ip_version=getattr(host, "mihomo_ip_version", None),
        external_proxy=getattr(host, "external_proxy", None),
        node_ids=getattr(host, "node_ids", None),
        region=getattr(host, "region", None),
    )


def get_hosts(db: Session, inbound_tag: str) -> List[ProxyHost]:
    """
    Retrieves hosts for a given inbound tag.

    Args:
        db (Session): Database session.
        inbound_tag (str): The tag of the inbound.

    Returns:
        List[ProxyHost]: List of hosts for the inbound.
    """
    inbound = get_or_create_inbound(db, inbound_tag)
    return sorted(inbound.hosts, key=lambda h: (h.sort_order or 0, h.id or 0))


def get_hosts_existing(db: Session, inbound_tag: str) -> List[ProxyHost]:
    """Like ``get_hosts`` but never creates the inbound / default host row.

    Used for native ``__native:*`` host buckets so listing Hosts does not
    invent a ``{SERVER_IP}`` WireGuard endpoint until the operator adds one.
    """
    inbound = db.query(ProxyInbound).filter(ProxyInbound.tag == inbound_tag).first()
    if not inbound:
        return []
    return sorted(inbound.hosts, key=lambda h: (h.sort_order or 0, h.id or 0))


def add_host(db: Session, inbound_tag: str, host: ProxyHostModify) -> List[ProxyHost]:
    """
    Adds a new host to a proxy inbound.

    Args:
        db (Session): Database session.
        inbound_tag (str): The tag of the inbound.
        host (ProxyHostModify): Host details to be added.

    Returns:
        List[ProxyHost]: Updated list of hosts for the inbound.
    """
    inbound = get_or_create_inbound(db, inbound_tag)
    inbound.hosts.append(_proxy_host_row(inbound, host))
    db.commit()
    db.refresh(inbound)
    return inbound.hosts


def update_hosts(db: Session, inbound_tag: str, modified_hosts: List[ProxyHostModify]) -> List[ProxyHost]:
    """
    Updates hosts for a given inbound tag.

    Args:
        db (Session): Database session.
        inbound_tag (str): The tag of the inbound.
        modified_hosts (List[ProxyHostModify]): List of modified hosts.

    Returns:
        List[ProxyHost]: Updated list of hosts for the inbound.
    """
    inbound = get_or_create_inbound(db, inbound_tag)
    inbound.hosts = [_proxy_host_row(inbound, host) for host in modified_hosts]
    db.commit()
    db.refresh(inbound)
    return inbound.hosts


def get_user_queryset(db: Session) -> Query:
    """
    Retrieves the base user query with joined admin details.

    Args:
        db (Session): Database session.

    Returns:
        Query: Base user query.
    """
    return (
        db.query(User)
        .options(joinedload(User.admin))
        .options(joinedload(User.next_plan))
        .options(joinedload(User.proxies).joinedload(Proxy.excluded_inbounds))
    )


def get_user(db: Session, username: str) -> Optional[User]:
    """
    Retrieves a user by username.

    Args:
        db (Session): Database session.
        username (str): The username of the user.

    Returns:
        Optional[User]: The user object if found, else None.
    """
    return get_user_queryset(db).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """
    Retrieves a user by user ID.

    Args:
        db (Session): Database session.
        user_id (int): The ID of the user.

    Returns:
        Optional[User]: The user object if found, else None.
    """
    return get_user_queryset(db).filter(User.id == user_id).first()


def get_user_by_sub_token(db: Session, sub_token: str) -> Optional[User]:
    """Look up a user by their independent subscription token (32-char hex)."""
    if not sub_token:
        return None
    return get_user_queryset(db).filter(User.sub_token == sub_token.lower()).first()


UsersSortingOptions = Enum('UsersSortingOptions', {
    'username': User.username.asc(),
    'used_traffic': User.used_traffic.asc(),
    'data_limit': User.data_limit.asc(),
    'expire': User.expire.asc(),
    'created_at': User.created_at.asc(),
    'id': User.id.asc(),
    '-username': User.username.desc(),
    '-used_traffic': User.used_traffic.desc(),
    '-data_limit': User.data_limit.desc(),
    '-expire': User.expire.desc(),
    '-created_at': User.created_at.desc(),
    '-id': User.id.desc(),
})

_DEFAULT_USER_ORDER = (User.created_at.asc(), User.id.asc())


def _apply_user_list_filters(
    db: Session,
    query: Query,
    *,
    search: Optional[str] = None,
    usernames: Optional[List[str]] = None,
    status: Optional[Union[UserStatus, list]] = None,
    reset_strategy: Optional[Union[UserDataLimitResetStrategy, list]] = None,
    admin: Optional[Admin] = None,
    admins: Optional[List[str]] = None,
    protocol: Optional[str] = None,
    inbound_tag: Optional[str] = None,
    source_slug: Optional[str] = None,
    expiring_within_days: Optional[int] = None,
    near_limit_percent: Optional[int] = None,
) -> Query:
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.note.ilike(f"%{search}%"),
                User.sub_token.ilike(f"%{search}%"),
            )
        )

    if usernames:
        query = query.filter(User.username.in_(usernames))

    if status:
        if isinstance(status, list):
            query = query.filter(User.status.in_(status))
        else:
            query = query.filter(User.status == status)

    if reset_strategy:
        if isinstance(reset_strategy, list):
            query = query.filter(User.data_limit_reset_strategy.in_(reset_strategy))
        else:
            query = query.filter(User.data_limit_reset_strategy == reset_strategy)

    if admin:
        query = query.filter(User.admin == admin)

    if admins:
        query = query.filter(User.admin.has(Admin.username.in_(admins)))

    if protocol:
        try:
            proxy_type = ProxyTypes(protocol.lower())
            query = query.filter(User.proxies.any(Proxy.type == proxy_type))
        except ValueError:
            query = query.filter(False)

    if inbound_tag:
        from app import xray

        inbound = xray.config.inbounds_by_tag.get(inbound_tag)
        if not inbound:
            query = query.filter(False)
        else:
            proto_str = str(inbound.get("protocol") or "").lower()
            try:
                proxy_type = ProxyTypes(proto_str)
            except ValueError:
                query = query.filter(False)
            else:
                excluded_subq = (
                    db.query(Proxy.user_id)
                    .join(
                        excluded_inbounds_association,
                        Proxy.id == excluded_inbounds_association.c.proxy_id,
                    )
                    .filter(
                        excluded_inbounds_association.c.inbound_tag == inbound_tag,
                        Proxy.type == proxy_type,
                    )
                )
                query = query.filter(
                    User.proxies.any(Proxy.type == proxy_type),
                    ~User.id.in_(excluded_subq),
                )

    if source_slug:
        slug = source_slug.strip()
        if slug:
            query = query.filter(User.username.like(f"{slug}_%"))

    if expiring_within_days is not None and expiring_within_days > 0:
        now = int(time.time())
        deadline = now + expiring_within_days * 86400
        query = query.filter(
            User.expire.isnot(None),
            User.expire > now,
            User.expire <= deadline,
        )

    if near_limit_percent is not None and near_limit_percent > 0:
        query = query.filter(
            User.data_limit.isnot(None),
            User.data_limit > 0,
            User.used_traffic * 100 >= User.data_limit * near_limit_percent,
        )

    return query


def get_users(db: Session,
              offset: Optional[int] = None,
              limit: Optional[int] = None,
              usernames: Optional[List[str]] = None,
              search: Optional[str] = None,
              status: Optional[Union[UserStatus, list]] = None,
              sort: Optional[List[UsersSortingOptions]] = None,
              admin: Optional[Admin] = None,
              admins: Optional[List[str]] = None,
              reset_strategy: Optional[Union[UserDataLimitResetStrategy, list]] = None,
              protocol: Optional[str] = None,
              inbound_tag: Optional[str] = None,
              source_slug: Optional[str] = None,
              expiring_within_days: Optional[int] = None,
              near_limit_percent: Optional[int] = None,
              return_with_count: bool = False) -> Union[List[User], Tuple[List[User], int]]:
    """
    Retrieves users based on various filters and options.

    Args:
        db (Session): Database session.
        offset (Optional[int]): Number of records to skip.
        limit (Optional[int]): Number of records to retrieve.
        usernames (Optional[List[str]]): List of usernames to filter by.
        search (Optional[str]): Search term to filter by username or note.
        status (Optional[Union[UserStatus, list]]): User status or list of statuses to filter by.
        sort (Optional[List[UsersSortingOptions]]): Sorting options.
        admin (Optional[Admin]): Admin to filter users by.
        admins (Optional[List[str]]): List of admin usernames to filter users by.
        reset_strategy (Optional[Union[UserDataLimitResetStrategy, list]]): Data limit reset strategy to filter by.
        return_with_count (bool): Whether to return the total count of users.

    Returns:
        Union[List[User], Tuple[List[User], int]]: List of users or tuple of users and total count.
    """
    query = get_user_queryset(db)
    query = _apply_user_list_filters(
        db,
        query,
        search=search,
        usernames=usernames,
        status=status,
        reset_strategy=reset_strategy,
        admin=admin,
        admins=admins,
        protocol=protocol,
        inbound_tag=inbound_tag,
        source_slug=source_slug,
        expiring_within_days=expiring_within_days,
        near_limit_percent=near_limit_percent,
    )

    if return_with_count:
        count = query.count()

    if sort:
        query = query.order_by(*(opt.value for opt in sort))
    else:
        query = query.order_by(*_DEFAULT_USER_ORDER)

    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    if return_with_count:
        return query.all(), count

    return query.all()


def get_user_list_filter_options(
    db: Session,
    *,
    admin: Optional[Admin] = None,
) -> Dict[str, object]:
    """Source migration slugs and inbound tags for the users list filter UI."""
    from app import xray

    slug_set: List[str] = []
    seen: set[str] = set()
    for ep in list_subscription_endpoints(db):
        for candidate in (ep.legacy_panel_id, ep.slug):
            if candidate and candidate not in seen:
                seen.add(candidate)
                slug_set.append(candidate)

    base_q = db.query(User.id)
    if admin and not admin.is_sudo:
        base_q = base_q.filter(User.admin_id == admin.id)

    source_servers = []
    for slug in sorted(slug_set):
        count = base_q.filter(User.username.like(f"{slug}_%")).count()
        if count:
            source_servers.append({"slug": slug, "user_count": count})

    inbound_tags = sorted(xray.config.inbounds_by_tag.keys())
    protocols = sorted({str(v.value) for v in ProxyTypes})

    return {
        "source_servers": source_servers,
        "inbound_tags": inbound_tags,
        "protocols": protocols,
    }


def get_user_usages(db: Session, dbuser: User, start: datetime, end: datetime) -> List[UserUsageResponse]:
    """
    Retrieves user usages within a specified date range.

    Args:
        db (Session): Database session.
        dbuser (User): The user object.
        start (datetime): Start date for usage retrieval.
        end (datetime): End date for usage retrieval.

    Returns:
        List[UserUsageResponse]: List of user usage responses.
    """

    usages = {0: UserUsageResponse(  # Main Core
        node_id=None,
        node_name="Master",
        used_traffic=0
    )}

    for node in db.query(Node).all():
        usages[node.id] = UserUsageResponse(
            node_id=node.id,
            node_name=node.name,
            used_traffic=0
        )

    cond = and_(NodeUserUsage.user_id == dbuser.id,
                NodeUserUsage.created_at >= start,
                NodeUserUsage.created_at <= end)

    for v in db.query(NodeUserUsage).filter(cond):
        try:
            usages[v.node_id or 0].used_traffic += v.used_traffic
        except KeyError:
            pass

    return list(usages.values())


def get_user_daily_usages(
    db: Session,
    dbuser: User,
    days: int = 7,
) -> List[UserDailyUsageDay]:
    """Aggregate ``NodeUserUsage`` into one bucket per UTC calendar day.

    Returns exactly ``days`` entries ending today (inclusive), with ``0`` for
    days that have no traffic rows.
    """
    days = max(1, min(int(days or 7), 90))
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())

    by_day: Dict[str, int] = {}
    rows = (
        db.query(NodeUserUsage.created_at, NodeUserUsage.used_traffic)
        .filter(
            NodeUserUsage.user_id == dbuser.id,
            NodeUserUsage.created_at >= start_dt,
            NodeUserUsage.created_at <= end_dt,
        )
        .all()
    )
    for created_at, used in rows:
        if created_at is None:
            continue
        key = created_at.date().isoformat()
        by_day[key] = by_day.get(key, 0) + int(used or 0)

    out: List[UserDailyUsageDay] = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        iso = d.isoformat()
        out.append(UserDailyUsageDay(date=iso, used_traffic=by_day.get(iso, 0)))
    return out


def get_users_count(db: Session, status: UserStatus = None, admin: Admin = None) -> int:
    """
    Retrieves the count of users based on status and admin filters.

    Args:
        db (Session): Database session.
        status (UserStatus, optional): Status to filter users by.
        admin (Admin, optional): Admin to filter users by.

    Returns:
        int: Count of users matching the criteria.
    """
    query = db.query(User.id)
    if admin:
        query = query.filter(User.admin == admin)
    if status:
        query = query.filter(User.status == status)
    return query.count()


def create_user(
    db: Session,
    user: UserCreate,
    admin: Admin = None,
    *,
    commit: bool = True,
    inbound_cache: Optional[Dict[str, ProxyInbound]] = None,
    skip_admin_limits: bool = False,
) -> User:
    """
    Creates a new user with provided details.

    Args:
        db (Session): Database session.
        user (UserCreate): User creation details.
        admin (Admin, optional): Admin associated with the user.
        inbound_cache: Optional shared tag->ProxyInbound cache (see
            ``get_or_create_inbound``) to speed up bulk imports.
        skip_admin_limits: When True, skip per-call max_users /
            max_total_traffic checks (caller already validated capacity).

    Returns:
        User: The created user object.
    """
    if not skip_admin_limits:
        if admin is not None and admin.max_users is not None:
            current = get_users_count(db, admin=admin)
            if current >= admin.max_users:
                raise ValueError(f"Reseller user limit reached ({admin.max_users})")

        if (
            admin is not None
            and not admin.is_sudo
            and admin.max_total_traffic is not None
            and int(admin.users_usage or 0) >= int(admin.max_total_traffic)
        ):
            raise ValueError(
                f"Reseller total-traffic limit reached ({admin.max_total_traffic} bytes)"
            )

    excluded_inbounds_tags = user.excluded_inbounds
    proxies = []
    for proxy_type, settings in user.proxies.items():
        excluded_inbounds = [
            get_or_create_inbound(db, tag, inbound_cache=inbound_cache, commit=commit)
            for tag in excluded_inbounds_tags[proxy_type]
        ]
        proxies.append(
            Proxy(type=proxy_type.value,
                  settings=settings.dict(no_obj=True),
                  excluded_inbounds=excluded_inbounds)
        )

    dbuser = User(
        username=user.username,
        proxies=proxies,
        status=user.status,
        data_limit=(user.data_limit or None),
        expire=(user.expire or None),
        admin=admin,
        data_limit_reset_strategy=user.data_limit_reset_strategy,
        note=user.note,
        on_hold_expire_duration=(user.on_hold_expire_duration or None),
        on_hold_timeout=(user.on_hold_timeout or None),
        auto_delete_in_days=user.auto_delete_in_days,
        client_profile=(user.client_profile or "normal"),
        session_limit_minutes=getattr(user, "session_limit_minutes", None) or None,
        device_limit=getattr(user, "device_limit", None),
        speed_limit_up=getattr(user, "speed_limit_up", None),
        speed_limit_down=getattr(user, "speed_limit_down", None),
        routing_preset=getattr(user, "routing_preset", None),
        dns_policy=getattr(user, "dns_policy", None),
        sub_token=secrets.token_hex(16),
        next_plan=NextPlan(
            data_limit=user.next_plan.data_limit,
            expire=user.next_plan.expire,
            add_remaining_traffic=user.next_plan.add_remaining_traffic,
            fire_on_either=user.next_plan.fire_on_either,
        ) if user.next_plan else None
    )
    if user.portal_enabled or user.portal_password:
        from app.models.admin import pwd_context

        if user.portal_password:
            dbuser.hashed_portal_password = pwd_context.hash(user.portal_password)
        dbuser.portal_enabled = user.portal_enabled or bool(user.portal_password)
        dbuser.portal_password_reset_at = datetime.utcnow()
    db.add(dbuser)
    if commit:
        db.commit()
        db.refresh(dbuser)
    else:
        db.flush()
    if user.portal_enabled or user.portal_password:
        from app.client.provision import ensure_app_proxies

        ensure_app_proxies(db, dbuser)
        if commit:
            db.refresh(dbuser)
    return dbuser


def repair_shadowsocks_methods(db: Session) -> int:
    """Align stored SS cipher with assigned inbounds for existing users."""
    from app import xray
    from app.xray.inbound_match import repair_shadowsocks_proxy_settings

    fixed = 0
    users = db.query(User).options(
        joinedload(User.proxies).joinedload(Proxy.excluded_inbounds),
    ).all()
    for user in users:
        ss_proxy = next((p for p in user.proxies if p.type == ProxyTypes.Shadowsocks), None)
        if not ss_proxy:
            continue
        excluded = {i.tag for i in ss_proxy.excluded_inbounds}
        tags = [
            inbound["tag"]
            for inbound in xray.config.product_inbounds_for_type(ProxyTypes.Shadowsocks)
            if inbound["tag"] not in excluded
        ]
        if not tags:
            continue
        patched = repair_shadowsocks_proxy_settings(ss_proxy.settings, tags)
        if patched:
            ss_proxy.settings = patched
            fixed += 1
    if fixed:
        db.commit()
    return fixed


def _purge_user_dependents(db: Session, user_ids: List[int]) -> None:
    """Clear rows that reference these users but have no ORM/DB delete-cascade.

    Several analytics/order tables carry a plain ``user_id`` FK (no
    ``ON DELETE CASCADE`` and not mapped as a cascading relationship on
    ``User``). Without clearing them first, PostgreSQL rejects the user delete
    with a ForeignKeyViolation — which previously aborted the whole bulk delete
    so *nothing* was removed. Nullable references (financial records, reserved
    IPs) are detached rather than deleted so they survive as history / pool.
    """
    if not user_ids:
        return

    from app.db.models import ClientDevice, PaymentIntent, PortalPushSubscription

    # Hard-delete pure per-user analytics / logs / orders / membership rows.
    #
    # ``SubscriptionTokenAlias`` / ``WgPeer`` already have ON DELETE CASCADE at
    # the DB, but we still clear aliases explicitly so older in-memory builds
    # (pre-restart) don't try to NULL the NOT NULL column.
    for model in (
        SubscriptionTokenAlias,
        NodeUserProtocolUsage,
        NodeUserUsage,
        NotificationReminder,
        NextPlan,
        ClientProbe,
        ClientTelemetry,
        ClientDevice,
        PortalPushSubscription,
        UserOrder,
        UserUsageResetLogs,
    ):
        db.query(model).filter(model.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )

    # Proxies have NO ACTION FK + M2M exclude rows — must go before users.
    proxy_ids = [
        int(pid)
        for (pid,) in db.query(Proxy.id).filter(Proxy.user_id.in_(user_ids)).all()
    ]
    if proxy_ids:
        db.execute(
            excluded_inbounds_association.delete().where(
                excluded_inbounds_association.c.proxy_id.in_(proxy_ids)
            )
        )
        db.query(Proxy).filter(Proxy.id.in_(proxy_ids)).delete(
            synchronize_session=False
        )

    # Detach nullable references we want to keep: payment history and the
    # dedicated-IP pool (freed IPs return to the pool instead of vanishing).
    db.query(PaymentIntent).filter(PaymentIntent.user_id.in_(user_ids)).update(
        {PaymentIntent.user_id: None}, synchronize_session=False
    )
    db.query(DedicatedIP).filter(DedicatedIP.user_id.in_(user_ids)).update(
        {DedicatedIP.user_id: None, DedicatedIP.assigned_at: None},
        synchronize_session=False,
    )


def remove_user(db: Session, dbuser: User) -> User:
    """
    Removes a user from the database.

    Args:
        db (Session): Database session.
        dbuser (User): The user object to be removed.

    Returns:
        User: The removed user object.
    """
    uid = int(dbuser.id)
    remove_users_by_ids(db, [uid])
    return dbuser


def remove_users_by_ids(db: Session, user_ids: List[int]) -> int:
    """Bulk-delete users by primary key (one purge + one DELETE)."""
    ids = [int(i) for i in user_ids if i is not None]
    if not ids:
        return 0
    _purge_user_dependents(db, ids)
    deleted = (
        db.query(User)
        .filter(User.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def remove_users(db: Session, dbusers: List[User]):
    """
    Removes multiple users from the database.

    Uses bulk SQL deletes instead of per-row ORM ``db.delete`` (which was
    loading cascades and taking ~40ms+/user on flush).
    """
    return remove_users_by_ids(
        db, [int(u.id) for u in dbusers if getattr(u, "id", None) is not None]
    )


def ensure_bulk_delete_indexes(db: Session) -> None:
    """Indexes required for fast FK checks during bulk user/proxy deletes.

    Without ``exclude_inbounds_association(proxy_id)`` and
    ``node_user_usages(user_id)``, PostgreSQL RI triggers seq-scan hundreds of
    thousands of rows per deleted proxy/user (~500ms+ for 50 users).
    """
    import logging

    from sqlalchemy import text

    log = logging.getLogger("shahkar")
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_exclude_inbounds_association_proxy_id "
        "ON exclude_inbounds_association (proxy_id)",
        "CREATE INDEX IF NOT EXISTS ix_node_user_usages_user_id "
        "ON node_user_usages (user_id)",
    ):
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception:
            db.rollback()
            log.exception("ensure_bulk_delete_indexes failed: %s", stmt)


def update_user(
    db: Session,
    dbuser: User,
    modify: UserModify,
    *,
    commit: bool = True,
    inbound_cache: Optional[Dict[str, ProxyInbound]] = None,
) -> User:
    """
    Updates a user with new details.

    Args:
        db (Session): Database session.
        dbuser (User): The user object to be updated.
        modify (UserModify): New details for the user.
        inbound_cache: Optional shared tag->ProxyInbound cache (see
            ``get_or_create_inbound``) to speed up bulk imports.

    Returns:
        User: The updated user object.
    """
    from app.models.proxy import apply_proxy_patch

    needs_disconnect = False
    added_proxies: Dict[ProxyTypes, Proxy] = {}
    if modify.proxies:
        for proxy_type, patch in modify.proxies.items():
            dbproxy = db.query(Proxy) \
                .where(Proxy.user == dbuser, Proxy.type == proxy_type) \
                .first()
            if dbproxy:
                dbproxy.settings = apply_proxy_patch(proxy_type, dbproxy.settings, patch)
            else:
                new_proxy = Proxy(
                    type=proxy_type,
                    settings=apply_proxy_patch(proxy_type, None, patch),
                )
                dbuser.proxies.append(new_proxy)
                added_proxies.update({proxy_type: new_proxy})
        for proxy in dbuser.proxies:
            if proxy.type not in modify.proxies:
                db.delete(proxy)
    if modify.inbounds:
        for proxy_type, tags in modify.excluded_inbounds.items():
            dbproxy = db.query(Proxy) \
                .where(Proxy.user == dbuser, Proxy.type == proxy_type) \
                .first() or added_proxies.get(proxy_type)
            if dbproxy:
                dbproxy.excluded_inbounds = [
                    get_or_create_inbound(db, tag, inbound_cache=inbound_cache, commit=commit)
                    for tag in tags
                ]

        from app.xray.inbound_match import repair_shadowsocks_proxy_settings

        ss_tags = modify.inbounds.get(ProxyTypes.Shadowsocks) or modify.inbounds.get("shadowsocks")
        if ss_tags:
            ss_proxy = db.query(Proxy).where(Proxy.user == dbuser, Proxy.type == ProxyTypes.Shadowsocks).first()
            if ss_proxy:
                patched = repair_shadowsocks_proxy_settings(ss_proxy.settings, ss_tags)
                if patched:
                    ss_proxy.settings = patched

    explicit_status = modify.status
    if explicit_status is not None:
        dbuser.status = explicit_status
        if explicit_status in (UserStatus.disabled, UserStatus.expired, UserStatus.limited):
            dbuser.online_at = None
            needs_disconnect = True
        dbuser.last_status_change = datetime.utcnow()

    if modify.data_limit is not None:
        dbuser.data_limit = (modify.data_limit or None)
        if dbuser.data_limit:
            from app.quota import apply_overage_on_recharge

            apply_overage_on_recharge(dbuser, dbuser.data_limit)
            if int(dbuser.used_traffic or 0) > int(dbuser.data_limit):
                dbuser.used_traffic = int(dbuser.data_limit)
        else:
            from app.quota import apply_overage_on_recharge

            apply_overage_on_recharge(dbuser, 0)
        if explicit_status is None and dbuser.status not in (UserStatus.expired, UserStatus.disabled):
            if not dbuser.data_limit or dbuser.used_traffic < dbuser.data_limit:
                if dbuser.status != UserStatus.on_hold:
                    dbuser.status = UserStatus.active

                for percent in sorted(NOTIFY_REACHED_USAGE_PERCENT, reverse=True):
                    if not dbuser.data_limit or (calculate_usage_percent(
                            dbuser.used_traffic, dbuser.data_limit) < percent):
                        reminder = get_notification_reminder(db, dbuser.id, ReminderType.data_usage, threshold=percent)
                        if reminder:
                            delete_notification_reminder(db, reminder)

            elif explicit_status is None:
                dbuser.status = UserStatus.limited
                needs_disconnect = True
        elif (
            explicit_status is None
            and dbuser.data_limit
            and int(dbuser.used_traffic or 0) >= int(dbuser.data_limit)
            and dbuser.status == UserStatus.limited
        ):
            needs_disconnect = True

    if modify.expire is not None:
        dbuser.expire = (modify.expire or None)
        if explicit_status is None and dbuser.status in (UserStatus.active, UserStatus.expired):
            if not dbuser.expire or dbuser.expire > datetime.utcnow().timestamp():
                dbuser.status = UserStatus.active
                for days_left in sorted(NOTIFY_DAYS_LEFT):
                    if not dbuser.expire or (calculate_expiration_days(
                            dbuser.expire) > days_left):
                        reminder = get_notification_reminder(
                            db, dbuser.id, ReminderType.expiration_date, threshold=days_left)
                        if reminder:
                            delete_notification_reminder(db, reminder)
            else:
                dbuser.status = UserStatus.expired

    if modify.note is not None:
        dbuser.note = modify.note or None

    if modify.client_profile is not None:
        dbuser.client_profile = modify.client_profile

    if modify.data_limit_reset_strategy is not None:
        dbuser.data_limit_reset_strategy = modify.data_limit_reset_strategy.value

    if modify.on_hold_timeout is not None:
        dbuser.on_hold_timeout = modify.on_hold_timeout

    if modify.on_hold_expire_duration is not None:
        dbuser.on_hold_expire_duration = modify.on_hold_expire_duration

    if modify.next_plan is not None:
        dbuser.next_plan = NextPlan(
            data_limit=modify.next_plan.data_limit,
            expire=modify.next_plan.expire,
            add_remaining_traffic=modify.next_plan.add_remaining_traffic,
            fire_on_either=modify.next_plan.fire_on_either,
        )
    elif dbuser.next_plan is not None:
        db.delete(dbuser.next_plan)

    fields_set = getattr(modify, "model_fields_set", set())
    if "routing_preset" in fields_set:
        dbuser.routing_preset = modify.routing_preset or None
    if "dns_policy" in fields_set:
        dbuser.dns_policy = modify.dns_policy
    if "session_limit_minutes" in fields_set:
        dbuser.session_limit_minutes = modify.session_limit_minutes or None
    if "device_limit" in fields_set:
        dbuser.device_limit = modify.device_limit or None
    if "speed_limit_up" in fields_set:
        dbuser.speed_limit_up = modify.speed_limit_up or None
    if "speed_limit_down" in fields_set:
        dbuser.speed_limit_down = modify.speed_limit_down or None

    if modify.portal_enabled is not None:
        dbuser.portal_enabled = modify.portal_enabled
        if not modify.portal_enabled:
            dbuser.hashed_portal_password = None

    if modify.portal_password:
        from app.models.admin import pwd_context
        dbuser.hashed_portal_password = pwd_context.hash(modify.portal_password)
        dbuser.portal_enabled = True
        dbuser.portal_password_reset_at = datetime.utcnow()

    if modify.portal_enabled or modify.portal_password:
        from app.client.provision import ensure_app_proxies

        ensure_app_proxies(db, dbuser)

    dbuser.edit_at = datetime.utcnow()

    from app.quota import reactivate_if_quota_available, disconnect_user_everywhere

    # Do not undo an admin-forced ``limited`` unless they also changed the package.
    if explicit_status != UserStatus.limited or modify.data_limit is not None:
        reactivate_if_quota_available(dbuser)
    if dbuser.status == UserStatus.active:
        needs_disconnect = False

    if commit:
        db.commit()
        db.refresh(dbuser)
        if needs_disconnect:
            disconnect_user_everywhere(dbuser)
    else:
        db.flush()

    return dbuser


def reset_user_data_usage(db: Session, dbuser: User) -> User:
    """
    Resets the data usage of a user and logs the reset.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose data usage is to be reset.

    Returns:
        User: The updated user object.
    """
    usage_log = UserUsageResetLogs(
        user=dbuser,
        used_traffic_at_reset=dbuser.used_traffic,
    )
    db.add(usage_log)

    dbuser.used_traffic = 0
    dbuser.used_traffic_up = 0
    dbuser.used_traffic_down = 0
    dbuser.overage_traffic = 0
    dbuser.node_usages.clear()
    if dbuser.status not in (UserStatus.expired, UserStatus.disabled):
        dbuser.status = UserStatus.active

    if dbuser.next_plan:
        db.delete(dbuser.next_plan)
        dbuser.next_plan = None
    db.add(dbuser)

    db.commit()
    db.refresh(dbuser)
    return dbuser


def reset_user_by_next(db: Session, dbuser: User) -> User:
    """
    Resets the data usage of a user based on next user.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose data usage is to be reset.

    Returns:
        User: The updated user object.
    """

    if (dbuser.next_plan is None):
        return

    usage_log = UserUsageResetLogs(
        user=dbuser,
        used_traffic_at_reset=dbuser.used_traffic,
    )
    db.add(usage_log)

    dbuser.node_usages.clear()
    dbuser.status = UserStatus.active.value

    dbuser.data_limit = dbuser.next_plan.data_limit + \
        (0 if dbuser.next_plan.add_remaining_traffic else dbuser.data_limit - dbuser.used_traffic)
    # next_plan.expire is a *duration* in seconds (same unit as UserTemplate.
    # expire_duration), not an absolute timestamp. Convert it relative to now so
    # activating the next plan grants the intended window instead of an epoch in
    # the past. 0/None means "no expiry".
    if dbuser.next_plan.expire:
        dbuser.expire = int(
            (datetime.utcnow() + timedelta(seconds=dbuser.next_plan.expire)).timestamp()
        )
    else:
        dbuser.expire = None

    dbuser.used_traffic = 0
    dbuser.used_traffic_up = 0
    dbuser.used_traffic_down = 0
    dbuser.overage_traffic = 0
    db.delete(dbuser.next_plan)
    dbuser.next_plan = None
    db.add(dbuser)

    db.commit()
    db.refresh(dbuser)
    return dbuser


def revoke_user_sub(db: Session, dbuser: User) -> User:
    """
    Revokes the subscription of a user and updates proxies settings.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose subscription is to be revoked.

    Returns:
        User: The updated user object.
    """
    from app.models.proxy import ProxySettings

    dbuser.sub_revoked_at = datetime.utcnow()
    dbuser.sub_token = secrets.token_hex(16)

    # Rotate each proxy's credentials in place. We deliberately do NOT route this
    # through update_user(): that expects a UserModify (it reads modify-only
    # fields such as portal_password), whereas revoke only needs fresh secrets.
    for dbproxy in dbuser.proxies:
        settings = ProxySettings.from_dict(dbproxy.type, dbproxy.settings or {})
        settings.revoke()
        dbproxy.settings = settings.dict(no_obj=True)

    db.commit()
    db.refresh(dbuser)
    return dbuser


def rotate_user_sub_link(db: Session, dbuser: User) -> User:
    """Rotate subscription URL only (sub_token); proxy credentials stay unchanged."""
    dbuser.sub_token = secrets.token_hex(16)
    dbuser.sub_revoked_at = None
    db.commit()
    db.refresh(dbuser)
    return dbuser


def set_user_sub_token(db: Session, dbuser: User, token: str) -> User:
    """Set a custom subscription token (link id) for the user."""
    import re

    token = (token or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]{8,32}", token):
        raise ValueError("Subscription id must be 8–32 lowercase letters or digits")
    other = get_user_by_sub_token(db, token)
    if other is not None and other.id != dbuser.id:
        raise ValueError("This subscription id is already taken")
    dbuser.sub_token = token
    dbuser.sub_revoked_at = None
    db.commit()
    db.refresh(dbuser)
    return dbuser


def set_portal_password(db: Session, dbuser: User, new_password: str) -> User:
    """Update the end-user portal password."""
    from app.models.admin import pwd_context

    if not new_password or len(new_password) < 4:
        raise ValueError("Password must be at least 4 characters")
    dbuser.hashed_portal_password = pwd_context.hash(new_password)
    dbuser.portal_enabled = True
    dbuser.portal_password_reset_at = datetime.utcnow()
    db.commit()
    db.refresh(dbuser)
    return dbuser


def ensure_portal_bootstrap(db: Session, dbuser: User) -> User:
    """Enable portal with initial password = username when not yet set.

    Sets ``must_change_credentials`` so the user must pick a new username and
    password before using the portal normally.
    """
    from app.models.admin import pwd_context

    needs_password = not dbuser.hashed_portal_password
    if not dbuser.portal_enabled or needs_password:
        dbuser.portal_enabled = True
        if needs_password:
            dbuser.hashed_portal_password = pwd_context.hash(dbuser.username)
            dbuser.portal_password_reset_at = datetime.utcnow()
        dbuser.must_change_credentials = True
        db.commit()
        db.refresh(dbuser)
        from app.client.provision import ensure_app_proxies

        ensure_app_proxies(db, dbuser)
    return dbuser


def complete_portal_setup(
    db: Session,
    dbuser: User,
    new_username: str,
    new_password: str,
) -> User:
    """First-login setup: rename VPN username and set a real portal password."""
    import re

    from app.models.admin import pwd_context

    if not getattr(dbuser, "must_change_credentials", False):
        raise ValueError("Credential setup is not required")

    username = (new_username or "").strip().lower()
    password = new_password or ""
    if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
        raise ValueError("Username must be 3–32 chars: a-z, 0-9, underscore")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")
    if password.lower() == username:
        raise ValueError("Password must not match username")
    if password == dbuser.username:
        raise ValueError("Choose a password different from the account id")

    old_username = dbuser.username
    if username != old_username.lower():
        other = get_user(db, username)
        if other is not None and other.id != dbuser.id:
            raise ValueError("Username is already taken")
        dbuser.username = username

    dbuser.hashed_portal_password = pwd_context.hash(password)
    dbuser.portal_enabled = True
    dbuser.must_change_credentials = False
    dbuser.portal_password_reset_at = datetime.utcnow()
    dbuser.edit_at = datetime.utcnow()
    db.commit()
    db.refresh(dbuser)

    if username != old_username.lower():
        try:
            from app.xray import operations as xray_ops

            xray_ops.update_user(dbuser)
        except Exception:
            pass
        try:
            from app.client.provision import ensure_app_proxies

            ensure_app_proxies(db, dbuser)
        except Exception:
            pass

    return dbuser


def update_user_sub(db: Session, dbuser: User, user_agent: str) -> User:
    """
    Updates the user's subscription details.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose subscription is to be updated.
        user_agent (str): The user agent string to update.

    Returns:
        User: The updated user object.
    """
    dbuser.sub_updated_at = datetime.utcnow()
    dbuser.sub_last_user_agent = user_agent

    db.commit()
    db.refresh(dbuser)
    return dbuser


def reset_all_users_data_usage(db: Session, admin: Optional[Admin] = None):
    """
    Resets the data usage for all users or users under a specific admin.

    Args:
        db (Session): Database session.
        admin (Optional[Admin]): Admin to filter users by, if any.
    """
    query = get_user_queryset(db)

    if admin:
        query = query.filter(User.admin == admin)

    for dbuser in query.all():
        dbuser.used_traffic = 0
        dbuser.used_traffic_up = 0
        dbuser.used_traffic_down = 0
        dbuser.overage_traffic = 0
        if dbuser.status not in [UserStatus.on_hold, UserStatus.expired, UserStatus.disabled]:
            dbuser.status = UserStatus.active
        dbuser.usage_logs.clear()
        dbuser.node_usages.clear()
        if dbuser.next_plan:
            db.delete(dbuser.next_plan)
            dbuser.next_plan = None
        db.add(dbuser)

    db.commit()


def disable_all_active_users(db: Session, admin: Optional[Admin] = None):
    """
    Disable all active users or users under a specific admin.

    Args:
        db (Session): Database session.
        admin (Optional[Admin]): Admin to filter users by, if any.
    """
    query = db.query(User).filter(User.status.in_((UserStatus.active, UserStatus.on_hold)))
    if admin:
        query = query.filter(User.admin == admin)

    query.update({User.status: UserStatus.disabled, User.last_status_change: datetime.utcnow()}, synchronize_session=False)

    db.commit()


def activate_all_disabled_users(db: Session, admin: Optional[Admin] = None):
    """
    Activate all disabled users or users under a specific admin.

    Args:
        db (Session): Database session.
        admin (Optional[Admin]): Admin to filter users by, if any.
    """
    query_for_active_users = db.query(User).filter(User.status == UserStatus.disabled)
    query_for_on_hold_users = db.query(User).filter(
        and_(
            User.status == UserStatus.disabled, User.expire.is_(
                None), User.on_hold_expire_duration.isnot(None), User.online_at.is_(None)
        ))
    if admin:
        query_for_active_users = query_for_active_users.filter(User.admin == admin)
        query_for_on_hold_users = query_for_on_hold_users.filter(User.admin == admin)

    query_for_on_hold_users.update(
        {User.status: UserStatus.on_hold, User.last_status_change: datetime.utcnow()}, synchronize_session=False)
    query_for_active_users.update(
        {User.status: UserStatus.active, User.last_status_change: datetime.utcnow()}, synchronize_session=False)

    db.commit()


def autodelete_expired_users(db: Session,
                             include_limited_users: bool = False) -> List[User]:
    """
    Deletes expired (optionally also limited) users whose auto-delete time has passed.

    Args:
        db (Session): Database session
        include_limited_users (bool, optional): Whether to delete limited users as well.
            Defaults to False.

    Returns:
        list[User]: List of deleted users.
    """
    target_status = (
        [UserStatus.expired] if not include_limited_users
        else [UserStatus.expired, UserStatus.limited]
    )

    auto_delete = coalesce(User.auto_delete_in_days, USERS_AUTODELETE_DAYS)

    query = db.query(
        User, auto_delete,  # Use global auto-delete days as fallback
    ).filter(
        auto_delete >= 0,  # Negative values prevent auto-deletion
        User.status.in_(target_status),
    ).options(joinedload(User.admin))

    # TODO: Handle time filter in query itself (NOTE: Be careful with sqlite's strange datetime handling)
    expired_users = [
        user
        for (user, auto_delete) in query
        if user.last_status_change + timedelta(days=auto_delete) <= datetime.utcnow()
    ]

    if expired_users:
        remove_users(db, expired_users)

    return expired_users


def get_all_users_usages(
        db: Session, admin: Admin, start: datetime, end: datetime
) -> List[UserUsageResponse]:
    """
    Retrieves usage data for all users associated with an admin within a specified time range.

    This function calculates the total traffic used by users across different nodes,
    including a "Master" node that represents the main core.

    Args:
        db (Session): Database session for querying.
        admin (Admin): The admin user for which to retrieve user usage data.
        start (datetime): The start date and time of the period to consider.
        end (datetime): The end date and time of the period to consider.

    Returns:
        List[UserUsageResponse]: A list of UserUsageResponse objects, each representing
        the usage data for a specific node or the main core.
    """
    usages = {0: UserUsageResponse(  # Main Core
        node_id=None,
        node_name="Master",
        used_traffic=0
    )}

    for node in db.query(Node).all():
        usages[node.id] = UserUsageResponse(
            node_id=node.id,
            node_name=node.name,
            used_traffic=0
        )

    admin_users = set(user.id for user in get_users(db=db, admins=admin))

    cond = and_(
        NodeUserUsage.created_at >= start,
        NodeUserUsage.created_at <= end,
        NodeUserUsage.user_id.in_(admin_users)
    )

    for v in db.query(NodeUserUsage).filter(cond):
        try:
            usages[v.node_id or 0].used_traffic += v.used_traffic
        except KeyError:
            pass

    return list(usages.values())


def update_user_status(db: Session, dbuser: User, status: UserStatus) -> User:
    """
    Updates a user's status and records the time of change.

    Args:
        db (Session): Database session.
        dbuser (User): The user to update.
        status (UserStatus): The new status.

    Returns:
        User: The updated user object.
    """
    dbuser.status = status
    if status in (UserStatus.disabled, UserStatus.expired, UserStatus.limited):
        dbuser.online_at = None
    dbuser.last_status_change = datetime.utcnow()
    db.commit()
    db.refresh(dbuser)
    return dbuser


def set_owner(db: Session, dbuser: User, admin: Admin) -> User:
    """
    Sets the owner (admin) of a user.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose owner is to be set.
        admin (Admin): The admin to set as owner.

    Returns:
        User: The updated user object.
    """
    dbuser.admin = admin
    db.commit()
    db.refresh(dbuser)
    return dbuser


def start_user_expire(db: Session, dbuser: User) -> User:
    """
    Starts the expiration timer for a user.

    Args:
        db (Session): Database session.
        dbuser (User): The user object whose expiration timer is to be started.

    Returns:
        User: The updated user object.
    """
    expire = int(datetime.utcnow().timestamp()) + dbuser.on_hold_expire_duration
    dbuser.expire = expire
    dbuser.on_hold_expire_duration = None
    dbuser.on_hold_timeout = None
    db.commit()
    db.refresh(dbuser)
    return dbuser


def get_system_usage(db: Session) -> System:
    """
    Retrieves system usage information.

    Args:
        db (Session): Database session.

    Returns:
        System: System usage information.
    """
    return db.query(System).first()


def get_jwt_secret_key(db: Session) -> str:
    """
    Retrieves the JWT secret key.

    Args:
        db (Session): Database session.

    Returns:
        str: JWT secret key.
    """
    row = db.query(JWT).first()
    if not row or not row.secret_key:
        raise RuntimeError("JWT secret is not configured in the database")
    return row.secret_key


def get_tls_certificate(db: Session) -> TLS:
    """
    Retrieves the TLS certificate.

    Args:
        db (Session): Database session.

    Returns:
        TLS: TLS certificate information.
    """
    return db.query(TLS).first()


def get_admin(db: Session, username: str) -> Admin:
    """
    Retrieves an admin by username.

    Args:
        db (Session): Database session.
        username (str): The username of the admin.

    Returns:
        Admin: The admin object.
    """
    return db.query(Admin).filter(Admin.username == username).first()


def ensure_db_admin(
    db: Session,
    username: str,
    *,
    is_sudo: bool = False,
) -> Optional[Admin]:
    """Return the ``admins`` row for ``username``, materializing env-only sudo.

    Env ``SUDO_USERNAME`` / ``SUDOERS`` can authenticate without an ``admins``
    row. Billing, wallets, and API keys need ``admin_id``, so the first call
    creates a sudo row (random unused password hash — login stays via env).
    Non-sudo callers that have no row get ``None``.
    """
    import secrets

    from app.models.admin import AdminCreate
    from sqlalchemy.exc import IntegrityError

    dbadmin = get_admin(db, username)
    if dbadmin is not None:
        return dbadmin
    if not is_sudo:
        return None
    try:
        return create_admin(
            db,
            AdminCreate(
                username=username,
                password=secrets.token_urlsafe(32),
                is_sudo=True,
            ),
        )
    except IntegrityError:
        db.rollback()
        return get_admin(db, username)


def create_admin(db: Session, admin: AdminCreate) -> Admin:
    """
    Creates a new admin in the database.

    Args:
        db (Session): Database session.
        admin (AdminCreate): The admin creation data.

    Returns:
        Admin: The created admin object.
    """
    dbadmin = Admin(
        username=admin.username,
        hashed_password=admin.hashed_password,
        is_sudo=admin.is_sudo,
        telegram_id=admin.telegram_id if admin.telegram_id else None,
        discord_webhook=admin.discord_webhook if admin.discord_webhook else None,
        role=getattr(admin, "role", None),
        max_users=getattr(admin, "max_users", None),
        max_total_traffic=getattr(admin, "max_total_traffic", None),
        max_nodes=getattr(admin, "max_nodes", None),
        parent_admin_id=getattr(admin, "parent_admin_id", None),
        commission_percent=int(getattr(admin, "commission_percent", 0) or 0),
    )
    db.add(dbadmin)
    db.commit()
    db.refresh(dbadmin)
    if dbadmin.parent_admin_id and dbadmin.tenant_id is None:
        parent = db.query(Admin).filter(Admin.id == dbadmin.parent_admin_id).first()
        if parent and parent.tenant_id is not None:
            dbadmin.tenant_id = parent.tenant_id
            db.commit()
            db.refresh(dbadmin)
    role = getattr(dbadmin, "role", None) or "reseller"
    if (
        not dbadmin.is_sudo
        and dbadmin.tenant_id is None
        and role in ("reseller", "support")
    ):
        from app.tenant import create_tenant

        tenant = create_tenant(
            db,
            name=dbadmin.username,
            slug=dbadmin.username,
            owner_admin_id=dbadmin.id,
            max_users=getattr(dbadmin, "max_users", None),
            max_nodes=getattr(dbadmin, "max_nodes", None),
        )
        dbadmin.tenant_id = tenant.id
        db.commit()
        db.refresh(dbadmin)
    if not dbadmin.is_sudo:
        try:
            from app import billing, feature_flags

            if feature_flags.is_enabled("billing"):
                billing.get_or_create_wallet(db, dbadmin.id)
        except Exception:
            pass
    return dbadmin


def update_admin(db: Session, dbadmin: Admin, modified_admin: AdminModify) -> Admin:
    """
    Updates an admin's details.

    Args:
        db (Session): Database session.
        dbadmin (Admin): The admin object to be updated.
        modified_admin (AdminModify): The modified admin data.

    Returns:
        Admin: The updated admin object.
    """
    if modified_admin.is_sudo:
        dbadmin.is_sudo = modified_admin.is_sudo
    if modified_admin.password is not None and dbadmin.hashed_password != modified_admin.hashed_password:
        dbadmin.hashed_password = modified_admin.hashed_password
        dbadmin.password_reset_at = datetime.utcnow()
    if modified_admin.telegram_id:
        dbadmin.telegram_id = modified_admin.telegram_id
    if modified_admin.discord_webhook:
        dbadmin.discord_webhook = modified_admin.discord_webhook
    fields_set = getattr(modified_admin, "model_fields_set", None) or set()
    for attr in (
        "role",
        "max_users",
        "max_total_traffic",
        "max_nodes",
        "commission_percent",
        "centralpay_enabled",
        "card_enabled",
        "card_number",
        "card_holder",
        "card_bank",
    ):
        if attr in fields_set:
            setattr(dbadmin, attr, getattr(modified_admin, attr))
        else:
            value = getattr(modified_admin, attr, None)
            if value is not None:
                setattr(dbadmin, attr, value)

    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def set_admin_totp_secret(db: Session, dbadmin: Admin, secret: Optional[str]) -> Admin:
    """Enable (secret) or disable (None) TOTP 2FA for an admin."""
    dbadmin.totp_secret = secret
    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def partial_update_admin(db: Session, dbadmin: Admin, modified_admin: AdminPartialModify) -> Admin:
    """
    Partially updates an admin's details.

    Args:
        db (Session): Database session.
        dbadmin (Admin): The admin object to be updated.
        modified_admin (AdminPartialModify): The modified admin data.

    Returns:
        Admin: The updated admin object.
    """
    if modified_admin.is_sudo is not None:
        dbadmin.is_sudo = modified_admin.is_sudo
    if modified_admin.password is not None and dbadmin.hashed_password != modified_admin.hashed_password:
        dbadmin.hashed_password = modified_admin.hashed_password
        dbadmin.password_reset_at = datetime.utcnow()
    if modified_admin.telegram_id is not None:
        dbadmin.telegram_id = modified_admin.telegram_id
    if modified_admin.discord_webhook is not None:
        dbadmin.discord_webhook = modified_admin.discord_webhook

    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def remove_admin(db: Session, dbadmin: Admin) -> Admin:
    """
    Removes an admin from the database.

    Args:
        db (Session): Database session.
        dbadmin (Admin): The admin object to be removed.

    Returns:
        Admin: The removed admin object.
    """
    db.delete(dbadmin)
    db.commit()
    return dbadmin


def get_admin_by_id(db: Session, id: int) -> Admin:
    """
    Retrieves an admin by their ID.

    Args:
        db (Session): Database session.
        id (int): The ID of the admin.

    Returns:
        Admin: The admin object.
    """
    return db.query(Admin).filter(Admin.id == id).first()


def get_admin_by_telegram_id(db: Session, telegram_id: int) -> Admin:
    """
    Retrieves an admin by their Telegram ID.

    Args:
        db (Session): Database session.
        telegram_id (int): The Telegram ID of the admin.

    Returns:
        Admin: The admin object.
    """
    return db.query(Admin).filter(Admin.telegram_id == telegram_id).first()


def get_admins(db: Session,
               offset: Optional[int] = None,
               limit: Optional[int] = None,
               username: Optional[str] = None) -> List[Admin]:
    """
    Retrieves a list of admins with optional filters and pagination.

    Args:
        db (Session): Database session.
        offset (Optional[int]): The number of records to skip (for pagination).
        limit (Optional[int]): The maximum number of records to return.
        username (Optional[str]): The username to filter by.

    Returns:
        List[Admin]: A list of admin objects.
    """
    query = db.query(Admin)
    if username:
        query = query.filter(Admin.username.ilike(f'%{username}%'))
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return query.all()


def reset_admin_usage(db: Session, dbadmin: Admin) -> int:
    """
    Retrieves an admin's usage by their username.
    Args:
        db (Session): Database session.
        dbadmin (Admin): The admin object to be updated.
    Returns:
        Admin: The updated admin.
    """
    if (dbadmin.users_usage == 0):
        return dbadmin

    usage_log = AdminUsageLogs(
        admin=dbadmin,
        used_traffic_at_reset=dbadmin.users_usage
    )
    db.add(usage_log)
    dbadmin.users_usage = 0

    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def create_user_template(db: Session, user_template: UserTemplateCreate) -> UserTemplate:
    """
    Creates a new user template in the database.

    Args:
        db (Session): Database session.
        user_template (UserTemplateCreate): The user template creation data.

    Returns:
        UserTemplate: The created user template object.
    """
    inbound_tags: List[str] = []
    for proto, tags in user_template.inbounds.items():
        proto_key = proto.value if hasattr(proto, "value") else str(proto)
        if proto_key in NATIVE_TEMPLATE_PROTOCOLS and not tags:
            inbound_tags.append(native_template_marker(proto_key))
        else:
            inbound_tags.extend(tags)
    inbound_records: List[ProxyInbound] = []
    for tag in inbound_tags:
        inbound_records.append(get_or_create_inbound(db, tag))
    dbuser_template = UserTemplate(
        name=user_template.name,
        data_limit=user_template.data_limit,
        expire_duration=user_template.expire_duration,
        username_prefix=user_template.username_prefix,
        username_suffix=user_template.username_suffix,
        data_limit_reset_strategy=getattr(user_template, "data_limit_reset_strategy", None),
        default_status=getattr(user_template, "default_status", None),
        note=getattr(user_template, "note", None),
        next_plan=(
            user_template.next_plan
            if isinstance(getattr(user_template, "next_plan", None), dict)
            else (
                user_template.next_plan.model_dump()
                if getattr(user_template, "next_plan", None) is not None
                else None
            )
        ),
        inbounds=inbound_records,
    )
    db.add(dbuser_template)
    db.commit()
    db.refresh(dbuser_template)
    return dbuser_template


def update_user_template(
        db: Session, dbuser_template: UserTemplate, modified_user_template: UserTemplateModify) -> UserTemplate:
    """
    Updates a user template's details.

    Args:
        db (Session): Database session.
        dbuser_template (UserTemplate): The user template object to be updated.
        modified_user_template (UserTemplateModify): The modified user template data.

    Returns:
        UserTemplate: The updated user template object.
    """
    if modified_user_template.name is not None:
        dbuser_template.name = modified_user_template.name
    if modified_user_template.data_limit is not None:
        dbuser_template.data_limit = modified_user_template.data_limit
    if modified_user_template.expire_duration is not None:
        dbuser_template.expire_duration = modified_user_template.expire_duration
    if modified_user_template.username_prefix is not None:
        dbuser_template.username_prefix = modified_user_template.username_prefix
    if modified_user_template.username_suffix is not None:
        dbuser_template.username_suffix = modified_user_template.username_suffix
    if getattr(modified_user_template, "data_limit_reset_strategy", None) is not None:
        dbuser_template.data_limit_reset_strategy = modified_user_template.data_limit_reset_strategy
    if getattr(modified_user_template, "default_status", None) is not None:
        dbuser_template.default_status = modified_user_template.default_status
    if getattr(modified_user_template, "note", None) is not None:
        dbuser_template.note = modified_user_template.note
    if getattr(modified_user_template, "next_plan", None) is not None:
        dbuser_template.next_plan = (
            modified_user_template.next_plan.model_dump()
            if modified_user_template.next_plan is not None
            else None
        )

    if modified_user_template.inbounds:
        inbound_tags: List[str] = []
        for proto, tags in modified_user_template.inbounds.items():
            proto_key = proto.value if hasattr(proto, "value") else str(proto)
            if proto_key in NATIVE_TEMPLATE_PROTOCOLS and not tags:
                inbound_tags.append(native_template_marker(proto_key))
            else:
                inbound_tags.extend(tags)
        inbound_records: List[ProxyInbound] = []
        for tag in inbound_tags:
            inbound_records.append(get_or_create_inbound(db, tag))
        dbuser_template.inbounds = inbound_records

    db.commit()
    db.refresh(dbuser_template)
    return dbuser_template


def remove_user_template(db: Session, dbuser_template: UserTemplate):
    """
    Removes a user template from the database.

    Args:
        db (Session): Database session.
        dbuser_template (UserTemplate): The user template object to be removed.
    """
    db.delete(dbuser_template)
    db.commit()


def get_user_template(db: Session, user_template_id: int) -> UserTemplate:
    """
    Retrieves a user template by its ID.

    Args:
        db (Session): Database session.
        user_template_id (int): The ID of the user template.

    Returns:
        UserTemplate: The user template object.
    """
    return db.query(UserTemplate).filter(UserTemplate.id == user_template_id).first()


def get_user_templates(
        db: Session, offset: Union[int, None] = None, limit: Union[int, None] = None) -> List[UserTemplate]:
    """
    Retrieves a list of user templates with optional pagination.

    Args:
        db (Session): Database session.
        offset (Union[int, None]): The number of records to skip (for pagination).
        limit (Union[int, None]): The maximum number of records to return.

    Returns:
        List[UserTemplate]: A list of user template objects.
    """
    dbuser_templates = db.query(UserTemplate)
    if offset:
        dbuser_templates = dbuser_templates.offset(offset)
    if limit:
        dbuser_templates = dbuser_templates.limit(limit)

    return dbuser_templates.all()


def get_node(db: Session, name: str) -> Optional[Node]:
    """
    Retrieves a node by its name.

    Args:
        db (Session): The database session.
        name (str): The name of the node to retrieve.

    Returns:
        Optional[Node]: The Node object if found, None otherwise.
    """
    return db.query(Node).filter(Node.name == name).first()


def get_node_by_id(db: Session, node_id: int) -> Optional[Node]:
    """
    Retrieves a node by its ID.

    Args:
        db (Session): The database session.
        node_id (int): The ID of the node to retrieve.

    Returns:
        Optional[Node]: The Node object if found, None otherwise.
    """
    return db.query(Node).filter(Node.id == node_id).first()


def get_nodes(db: Session,
              status: Optional[Union[NodeStatus, list]] = None,
              enabled: bool = None) -> List[Node]:
    """
    Retrieves nodes based on optional status and enabled filters.

    Args:
        db (Session): The database session.
        status (Optional[Union[NodeStatus, list]]): The status or list of statuses to filter by.
        enabled (bool): If True, excludes disabled nodes.

    Returns:
        List[Node]: A list of Node objects matching the criteria.
    """
    query = db.query(Node)

    if status:
        if isinstance(status, list):
            query = query.filter(Node.status.in_(status))
        else:
            query = query.filter(Node.status == status)

    if enabled:
        query = query.filter(Node.status != NodeStatus.disabled)

    return query.all()


def get_nodes_usage(db: Session, start: datetime, end: datetime) -> List[NodeUsageResponse]:
    """
    Retrieves usage data for all nodes within a specified time range.

    Args:
        db (Session): The database session.
        start (datetime): The start time of the usage period.
        end (datetime): The end time of the usage period.

    Returns:
        List[NodeUsageResponse]: A list of NodeUsageResponse objects containing usage data.
    """
    usages = {0: NodeUsageResponse(  # Main Core
        node_id=None,
        node_name="Master",
        uplink=0,
        downlink=0
    )}

    for node in db.query(Node).all():
        usages[node.id] = NodeUsageResponse(
            node_id=node.id,
            node_name=node.name,
            uplink=0,
            downlink=0
        )

    cond = and_(NodeUsage.created_at >= start, NodeUsage.created_at <= end)

    for v in db.query(NodeUsage).filter(cond):
        try:
            usages[v.node_id or 0].uplink += v.uplink
            usages[v.node_id or 0].downlink += v.downlink
        except KeyError:
            pass

    return list(usages.values())


def get_protocol_usage(
    db: Session,
    start: datetime,
    end: datetime,
    user_id: Optional[int] = None,
    admin_id: Optional[int] = None,
) -> List[dict]:
    """Aggregate hourly per-protocol usage in a date range.

    When ``admin_id`` is set (reseller workspace), only rows belonging to that
    admin's users are included — never the global/main-panel totals.
    """
    from sqlalchemy import func

    from app.db.models import NodeUserProtocolUsage

    cond = and_(
        NodeUserProtocolUsage.created_at >= start,
        NodeUserProtocolUsage.created_at <= end,
    )
    if user_id is not None:
        cond = and_(cond, NodeUserProtocolUsage.user_id == user_id)

    q = db.query(
        NodeUserProtocolUsage.protocol,
        func.sum(NodeUserProtocolUsage.used_traffic).label("bytes"),
    ).filter(cond)

    if admin_id is not None:
        q = q.join(User, User.id == NodeUserProtocolUsage.user_id).filter(
            User.admin_id == admin_id
        )

    rows = q.group_by(NodeUserProtocolUsage.protocol).all()
    return [{"protocol": r[0], "used_traffic": int(r[1] or 0)} for r in rows]


def create_node(db: Session, node: NodeCreate) -> Node:
    """
    Creates a new node in the database.

    Args:
        db (Session): The database session.
        node (NodeCreate): The node creation model containing node details.

    Returns:
        Node: The newly created Node object.
    """
    dbnode = Node(name=node.name,
                  address=node.address,
                  port=node.port,
                  api_port=node.api_port,
                  region=node.region,
                  capacity=node.capacity,
                  group_id=node.group_id,
                  core_kind=node.core_kind.value)

    db.add(dbnode)
    db.commit()
    db.refresh(dbnode)
    return dbnode


def remove_node(db: Session, dbnode: Node) -> Node:
    """
    Removes a node from the database.

    A handful of tables reference ``nodes.id`` without an ORM-managed cascade
    (only ``node_usages``/``node_user_usages``/``node_wireguard``/``node_singbox``
    cascade automatically via the ``Node`` relationships). Deleting a node that
    still has any of these references used to bubble up as a raw
    ``ForeignKeyViolation`` / 500 instead of a clean removal, most commonly
    when the node is one end of a Tunnel (relay/transit/exit).

    Returns:
        Node: The removed Node object.
    """
    node_id = dbnode.id

    # Tunnels cannot function with a missing endpoint — delete them outright
    # (mirrors the dedicated tunnel-delete endpoint) and revert the *other*
    # end's role back to "direct" if no other enabled tunnel still uses it.
    tunnels = db.query(Tunnel).filter(
        or_(
            Tunnel.relay_node_id == node_id,
            Tunnel.intermediate_node_id == node_id,
            Tunnel.exit_node_id == node_id,
        )
    ).all()
    other_node_ids = set()
    for tunnel in tunnels:
        for role_node_id in (tunnel.relay_node_id, tunnel.intermediate_node_id, tunnel.exit_node_id):
            if role_node_id is not None and role_node_id != node_id:
                other_node_ids.add(role_node_id)
        db.delete(tunnel)
    if tunnels:
        db.flush()
        for other_id in other_node_ids:
            still_used = db.query(Tunnel).filter(
                Tunnel.enabled.is_(True),
                or_(
                    Tunnel.relay_node_id == other_id,
                    Tunnel.intermediate_node_id == other_id,
                    Tunnel.exit_node_id == other_id,
                ),
            ).first()
            if not still_used:
                other_node = db.query(Node).filter(Node.id == other_id).first()
                if other_node is not None and other_node.role != "direct":
                    other_node.role = "direct"

    # Historical/analytics rows: safe to drop, they carry no independent value
    # once the node they describe no longer exists.
    db.query(NodeUserProtocolUsage).filter(NodeUserProtocolUsage.node_id == node_id).delete(
        synchronize_session=False
    )
    db.query(ClientProbe).filter(ClientProbe.node_id == node_id).delete(synchronize_session=False)
    db.query(ClientTelemetry).filter(ClientTelemetry.active_node == node_id).delete(
        synchronize_session=False
    )

    # A dedicated IP assignment outlives the node it happened to be bound to —
    # detach it instead of destroying the (billable) reservation.
    db.query(DedicatedIP).filter(DedicatedIP.node_id == node_id).update(
        {DedicatedIP.node_id: None}, synchronize_session=False
    )

    db.delete(dbnode)
    db.commit()
    return dbnode


def update_node(db: Session, dbnode: Node, modify: NodeModify) -> Node:
    """
    Updates an existing node with new information.

    Args:
        db (Session): The database session.
        dbnode (Node): The Node object to be updated.
        modify (NodeModify): The modification model containing updated node details.

    Returns:
        Node: The updated Node object.
    """
    if modify.name is not None:
        dbnode.name = modify.name

    if modify.address is not None:
        old_address = dbnode.address
        dbnode.address = modify.address
        from app.services.materialize import reconcile_singbox_sni, reconcile_wireguard_endpoints

        reconcile_wireguard_endpoints(db, dbnode)
        reconcile_singbox_sni(db, dbnode, old_address=old_address)

    if modify.port is not None:
        dbnode.port = modify.port

    if modify.api_port is not None:
        dbnode.api_port = modify.api_port

    if modify.status is NodeStatus.disabled:
        dbnode.status = modify.status
        dbnode.xray_version = None
        dbnode.message = None
    else:
        dbnode.status = NodeStatus.connecting

    if modify.usage_coefficient:
        dbnode.usage_coefficient = modify.usage_coefficient

    if modify.region is not None:
        dbnode.region = modify.region

    if modify.capacity is not None:
        dbnode.capacity = modify.capacity

    if modify.group_id is not None:
        dbnode.group_id = modify.group_id

    if modify.core_kind is not None:
        dbnode.core_kind = modify.core_kind.value

    if modify.warp_enabled is not None:
        dbnode.warp_enabled = bool(modify.warp_enabled)

    if modify.warp_tag is not None:
        tag = str(modify.warp_tag).strip() or None
        dbnode.warp_tag = tag

    db.commit()
    db.refresh(dbnode)
    return dbnode


def provision_wireguard_defaults(
    db: Session,
    dbnode: Node,
    *,
    listen_port: int = 51820,
    plain_enabled: bool = True,
    awg_enabled: bool = False,
) -> "NodeWireGuard":
    """Generate server keys and persist WG stack settings for a new WG node."""
    from app.wireguard import generate_keypair
    from app.wireguard.awg import random_awg_preset

    priv, pub = generate_keypair()
    endpoint = f"{dbnode.address}:{listen_port}"
    cfg = set_node_wireguard(
        db, dbnode,
        private_key=priv, public_key=pub,
        endpoint=endpoint, listen_port=listen_port,
    )
    cfg.plain_enabled = plain_enabled
    cfg.awg_enabled = awg_enabled
    if awg_enabled:
        awg_priv, awg_pub = generate_keypair()
        cfg.awg_private_key = awg_priv
        cfg.awg_public_key = awg_pub
        cfg.awg_endpoint = f"{dbnode.address}:{cfg.awg_listen_port}"
        for field, value in random_awg_preset().items():
            setattr(cfg, field, value)
    # Seed Finalmask inbound once so new nodes work without extra setup.
    # Ports are opened automatically on the node during sync.
    if cfg.xray_wg_listen_port is None:
        cfg.xray_wg_listen_port = 51901
        cfg.xray_wg_enabled = True
    db.commit()
    db.refresh(cfg)
    return cfg


def ensure_awg_server_keys(db: Session, dbnode: Node) -> "NodeWireGuard":
    """Ensure AmneziaWG server keys exist when the AWG listener is enabled."""
    from app.wireguard import generate_keypair

    cfg = dbnode.wireguard
    if cfg is None or not cfg.awg_enabled:
        return cfg
    if cfg.awg_private_key and cfg.awg_public_key:
        return cfg
    priv, pub = generate_keypair()
    cfg.awg_private_key = priv
    cfg.awg_public_key = pub
    if not cfg.awg_endpoint:
        cfg.awg_endpoint = f"{dbnode.address}:{cfg.awg_listen_port}"
    db.commit()
    db.refresh(cfg)
    return cfg


def _normalize_wg_client_endpoint(value: Optional[str], default_port: int) -> Optional[str]:
    """Accept ``host`` or ``host:port``; empty clears. Stores ``host:port``."""
    from app.subscription.wireguard import _endpoint_host

    raw = (value or "").strip()
    if not raw:
        return None
    host = _endpoint_host(raw)
    if not host:
        return None
    if raw.startswith("[") and "]:" in raw:
        return raw
    if raw.count(":") == 1:
        return raw
    port = int(default_port or 0)
    if port <= 0 or port > 65535:
        raise ValueError("endpoint needs a port (listen port is unset)")
    if ":" in host and not host.startswith("["):
        # IPv6 without brackets — wrap so clients parse host/port correctly.
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def set_node_wg_stack(
    db: Session,
    dbnode: Node,
    *,
    plain_enabled: Optional[bool] = None,
    awg_enabled: Optional[bool] = None,
    direct_listen_port: Optional[int] = None,
    endpoint: Optional[str] = None,
    awg_endpoint: Optional[str] = None,
    endpoint_set: bool = False,
    awg_endpoint_set: bool = False,
) -> "NodeWireGuard":
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if plain_enabled is not None:
        cfg.plain_enabled = plain_enabled
    if direct_listen_port is not None:
        # 0 clears/disables the parallel direct (untunneled) listener.
        if direct_listen_port == 0:
            cfg.direct_listen_port = None
        else:
            if direct_listen_port == cfg.listen_port or (
                cfg.awg_enabled and direct_listen_port == cfg.awg_listen_port
            ):
                raise ValueError("direct_listen_port must differ from listen_port/awg_listen_port")
            cfg.direct_listen_port = int(direct_listen_port)
    if awg_enabled is not None:
        cfg.awg_enabled = awg_enabled
        if awg_enabled:
            # ensure_awg_server_keys may commit when minting keys; do NOT
            # refresh here — a refresh would discard other dirty fields on
            # ``cfg`` (notably ``plain_enabled``) that have not been committed
            # yet, so "enable plain + awg" silently dropped plain.
            ensure_awg_server_keys(db, dbnode)
            if cfg.awg_jc is None:
                from app.wireguard.awg import random_awg_preset
                for field, value in random_awg_preset().items():
                    setattr(cfg, field, value)
    # Prefer explicit *_set flags; callers that pass endpoint= via kwargs treat
    # None as clear when endpoint_set is True (API maps "" → clear).
    if endpoint_set or endpoint is not None:
        cfg.endpoint = _normalize_wg_client_endpoint(
            endpoint, int(cfg.listen_port or 51820),
        )
    if awg_endpoint_set or awg_endpoint is not None:
        cfg.awg_endpoint = _normalize_wg_client_endpoint(
            awg_endpoint, int(cfg.awg_listen_port or 51821),
        )
    # All modes may be off (Xray-native-only, or fully disabled). Sync tears
    # down kernel interfaces when plain/AWG are disabled.
    db.commit()
    db.refresh(cfg)
    return cfg


def set_node_xray_wireguard(
    db: Session,
    dbnode: Node,
    *,
    enabled: Optional[bool] = None,
    listen_port: Optional[int] = None,
    mtu: Optional[int] = None,
    noise: Optional[dict] = None,
) -> "NodeWireGuard":
    """Configure the Xray-native WireGuard+Finalmask-noise inbound on a node.

    ``listen_port`` must differ from every other WG-family port already in
    use on this node (kernel plain/AWG/direct) — they're independent sockets
    that must not collide.
    """
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if listen_port is not None:
        taken = {cfg.listen_port}
        if cfg.awg_enabled:
            taken.add(cfg.awg_listen_port)
        if cfg.direct_listen_port:
            taken.add(cfg.direct_listen_port)
        if listen_port in taken:
            raise ValueError("xray_wg_listen_port must differ from every other WireGuard port on this node")
        cfg.xray_wg_listen_port = int(listen_port)
    if mtu is not None:
        cfg.xray_wg_mtu = int(mtu)
    if noise is not None:
        cfg.xray_wg_noise = noise or None
    if enabled is not None:
        if enabled and not cfg.xray_wg_listen_port:
            raise ValueError("Set xray_wg_listen_port before enabling the Xray-native WireGuard inbound")
        cfg.xray_wg_enabled = enabled
    db.commit()
    db.refresh(cfg)
    return cfg


def set_node_wireguard(db: Session, dbnode: Node, *, interface: str = "wg0",
                       listen_port: int = 51820, subnet: str = "10.10.0.0/16",
                       private_key: str, public_key: str,
                       endpoint: Optional[str] = None, mtu: int = 1420,
                       dns: Optional[str] = None) -> "NodeWireGuard":
    """Create or replace the per-node WireGuard server config (one-to-one)."""
    cfg = dbnode.wireguard
    if cfg is None:
        cfg = NodeWireGuard(node_id=dbnode.id)
        db.add(cfg)
    cfg.interface = interface
    cfg.listen_port = listen_port
    cfg.subnet = subnet
    cfg.private_key = private_key
    cfg.public_key = public_key
    cfg.endpoint = endpoint
    cfg.mtu = mtu
    cfg.dns = dns
    db.commit()
    db.refresh(cfg)
    return cfg


_AWG_FIELDS = (
    "awg_jc", "awg_jmin", "awg_jmax", "awg_s1", "awg_s2", "awg_s3", "awg_s4",
    "awg_h1", "awg_h2", "awg_h3", "awg_h4",
)


def set_node_sg_wire(db: Session, dbnode: Node, *, enabled: bool) -> "NodeWireGuard":
    """Enable/disable SigmaGuard Wire on a node and apply the deployment preset."""
    from app import feature_flags

    if not feature_flags.is_enabled("sigmaguard_wire"):
        raise ValueError("SigmaGuard Wire feature flag is disabled")
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if enabled:
        from app.sigmaguard_wire.bridge import apply_preset_to_node

        apply_preset_to_node(cfg)
        cfg.awg_enabled = True
        ensure_awg_server_keys(db, dbnode)
        cfg.sg_wire_enabled = True
    else:
        cfg.sg_wire_enabled = False
    db.commit()
    db.refresh(cfg)
    return cfg


def set_node_amnezia(db: Session, dbnode: Node, params: Dict[str, Optional[int]]) -> "NodeWireGuard":
    """Set/clear AmneziaWG obfuscation params on a node's WireGuard config.

    Only keys present in ``params`` are written; passing ``None`` clears one.
    Raises ``ValueError`` if the node has no WireGuard config yet.
    """
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    for field in _AWG_FIELDS:
        if field in params:
            setattr(cfg, field, params[field])
    if any(getattr(cfg, field, None) is not None for field in _AWG_FIELDS):
        cfg.awg_enabled = True
        ensure_awg_server_keys(db, dbnode)
    db.commit()
    db.refresh(cfg)
    return cfg


def get_wireguard_nodes(db: Session, enabled_only: bool = True) -> List[Node]:
    """Return nodes that serve WireGuard (legacy core_kind or service binding)."""
    wg_ids = (
        db.query(NodeServiceBinding.node_id)
        .filter(
            NodeServiceBinding.enabled.is_(True),
            NodeServiceBinding.service_slug.in_(("wireguard-plain", "amneziawg")),
        )
        .distinct()
    )
    query = (
        db.query(Node)
        .outerjoin(NodeWireGuard, NodeWireGuard.node_id == Node.id)
        .options(contains_eager(Node.wireguard))
        .filter(
            or_(
                Node.core_kind == CoreKind.wireguard.value,
                Node.id.in_(wg_ids),
                and_(
                    NodeWireGuard.node_id.isnot(None),
                    or_(
                        NodeWireGuard.plain_enabled.is_(True),
                        NodeWireGuard.awg_enabled.is_(True),
                        NodeWireGuard.xray_wg_enabled.is_(True),
                    ),
                ),
            )
        )
    )
    if enabled_only:
        query = query.filter(Node.status != NodeStatus.disabled)
    return query.distinct().all()


def get_singbox_nodes(db: Session, enabled_only: bool = True) -> List[Node]:
    """Return nodes that carry a sing-box config (Hysteria2/TUIC).

    Unlike WireGuard (a dedicated core_kind), sing-box runs *alongside* Xray on
    a normal node, so membership is defined by the presence of a NodeSingBox
    row with at least one protocol enabled.
    """
    query = (
        db.query(Node)
        .join(NodeSingBox, NodeSingBox.node_id == Node.id)
        .options(contains_eager(Node.singbox))
    )
    if enabled_only:
        query = query.filter(
            Node.status != NodeStatus.disabled,
            or_(
                NodeSingBox.hysteria2_enabled.is_(True),
                NodeSingBox.tuic_enabled.is_(True),
                NodeSingBox.anytls_enabled.is_(True),
            ),
        )
    return query.all()


def get_node_singbox(db: Session, dbnode: Node) -> Optional["NodeSingBox"]:
    return db.query(NodeSingBox).filter(NodeSingBox.node_id == dbnode.id).one_or_none()


def provision_singbox_defaults(
    db: Session,
    dbnode: Node,
    *,
    hysteria2: bool = True,
    tuic: bool = False,
    sni: Optional[str] = None,
) -> "NodeSingBox":
    """Seed Hysteria2/TUIC paths and ports for a new node."""
    from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY

    host = (sni or dbnode.address or "").strip()
    return upsert_node_singbox(
        db,
        dbnode,
        certificate_path=DEFAULT_CERT,
        key_path=DEFAULT_KEY,
        sni=host,
        hysteria2_enabled=hysteria2,
        hysteria2_port=44333 if hysteria2 else None,
        tuic_enabled=tuic,
        tuic_port=44334 if tuic else None,
    )


def upsert_node_singbox(db: Session, dbnode: Node, **fields) -> "NodeSingBox":
    """Create or update a node's sing-box config; only given fields are set."""
    cfg = get_node_singbox(db, dbnode)
    if cfg is None:
        cfg = NodeSingBox(node_id=dbnode.id)
        db.add(cfg)
    for key, value in fields.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    db.commit()
    db.refresh(cfg)
    return cfg


def seed_panel_services(db: Session) -> None:
    """Ensure catalog rows exist (idempotent)."""
    from app.services.catalog import SERVICE_SEEDS

    for row in SERVICE_SEEDS:
        existing = db.query(PanelService).filter(PanelService.slug == row["slug"]).first()
        if existing:
            continue
        db.add(
            PanelService(
                slug=row["slug"],
                display_name=row["display_name"],
                engine=row["engine"],
                protocol=row["protocol"],
                config=row.get("config") or {},
                sort_order=int(row.get("sort_order") or 0),
            )
        )
    db.commit()


def get_panel_services(db: Session, active_only: bool = True) -> List[PanelService]:
    q = db.query(PanelService).order_by(PanelService.sort_order, PanelService.slug)
    if active_only:
        q = q.filter(PanelService.is_active.is_(True))
    return q.all()


def get_node_service_bindings(
    db: Session, node_id: int, *, enabled_only: bool = False
) -> List[NodeServiceBinding]:
    q = (
        db.query(NodeServiceBinding)
        .options(joinedload(NodeServiceBinding.service))
        .filter(NodeServiceBinding.node_id == node_id)
    )
    if enabled_only:
        q = q.filter(NodeServiceBinding.enabled.is_(True))
    return q.all()


def set_node_service_bindings(
    db: Session,
    node_id: int,
    slugs: List[str],
    *,
    replace: bool = True,
) -> List[str]:
    """Enable ``slugs`` on a node; disable others when ``replace`` is True."""
    seed_panel_services(db)
    valid = {s.slug for s in get_panel_services(db)}
    slugs = [s for s in slugs if s in valid]

    if replace:
        db.query(NodeServiceBinding).filter(NodeServiceBinding.node_id == node_id).delete()

    enabled: List[str] = []
    for slug in slugs:
        row = (
            db.query(NodeServiceBinding)
            .filter(NodeServiceBinding.node_id == node_id, NodeServiceBinding.service_slug == slug)
            .first()
        )
        if row is None:
            row = NodeServiceBinding(node_id=node_id, service_slug=slug, enabled=True)
            db.add(row)
        else:
            row.enabled = True
        enabled.append(slug)
    db.commit()
    return enabled


def node_has_service(db: Session, node_id: int, slug: str) -> bool:
    return (
        db.query(NodeServiceBinding)
        .filter(
            NodeServiceBinding.node_id == node_id,
            NodeServiceBinding.service_slug == slug,
            NodeServiceBinding.enabled.is_(True),
        )
        .first()
        is not None
    )


def update_node_health(db: Session, dbnode: Node, latency_ms: Optional[float]) -> Node:
    """Record a successful health probe (latency + timestamp)."""
    dbnode.latency_ms = latency_ms
    dbnode.last_health = datetime.utcnow()
    db.commit()
    return dbnode


def create_node_group(db: Session, name: str, region: Optional[str] = None) -> NodeGroup:
    group = NodeGroup(name=name, region=region)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def get_node_groups(db: Session) -> List[NodeGroup]:
    return db.query(NodeGroup).order_by(NodeGroup.id).all()


def get_node_group_by_id(db: Session, group_id: int) -> Optional[NodeGroup]:
    return db.query(NodeGroup).filter(NodeGroup.id == group_id).first()


def remove_node_group(db: Session, group: NodeGroup) -> None:
    db.delete(group)
    db.commit()


def create_plan(db: Session, **kwargs) -> Plan:
    plan = Plan(**kwargs)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_plans(db: Session, enabled_only: bool = False) -> List[Plan]:
    query = db.query(Plan)
    if enabled_only:
        query = query.filter(Plan.enabled.is_(True))
    return query.order_by(Plan.id).all()


def get_plan_by_id(db: Session, plan_id: int) -> Optional[Plan]:
    return db.query(Plan).filter(Plan.id == plan_id).first()


def update_plan(db: Session, plan: Plan, **kwargs) -> Plan:
    for key, value in kwargs.items():
        if value is not None and hasattr(plan, key):
            setattr(plan, key, value)
    db.commit()
    db.refresh(plan)
    return plan


class PlanInUseError(Exception):
    """Raised when a plan cannot be hard-deleted because order history references it."""


def remove_plan(db: Session, plan: Plan) -> None:
    """Delete a plan after detaching nullable billing references.

    ``payment_intents`` / ``invoices`` keep their rows but lose the plan link.
    ``user_orders.plan_id`` is NOT NULL, so plans with orders cannot be removed
    — callers should catch ``PlanInUseError`` and return HTTP 409.
    """
    order_count = (
        db.query(func.count(UserOrder.id)).filter(UserOrder.plan_id == plan.id).scalar() or 0
    )
    if order_count:
        raise PlanInUseError(
            f"Plan is referenced by {int(order_count)} user order(s); "
            "disable it instead of deleting"
        )

    db.query(PaymentIntent).filter(PaymentIntent.plan_id == plan.id).update(
        {PaymentIntent.plan_id: None}, synchronize_session=False
    )
    db.query(Invoice).filter(Invoice.plan_id == plan.id).update(
        {Invoice.plan_id: None}, synchronize_session=False
    )
    db.delete(plan)
    db.commit()


def update_node_status(db: Session, dbnode: Node, status: NodeStatus, message: str = None, version: str = None) -> Node:
    """
    Updates the status of a node.

    Args:
        db (Session): The database session.
        dbnode (Node): The Node object to be updated.
        status (NodeStatus): The new status of the node.
        message (str, optional): A message associated with the status update.
        version (str, optional): The version of the node software.

    Returns:
        Node: The updated Node object.
    """
    dbnode.status = status
    dbnode.message = message
    if version is not None:
        from app.utils.xray_releases import normalize_xray_version_label

        dbnode.xray_version = normalize_xray_version_label(version)
    dbnode.last_status_change = datetime.utcnow()
    db.commit()
    db.refresh(dbnode)
    return dbnode


def create_notification_reminder(
        db: Session, reminder_type: ReminderType, expires_at: datetime, user_id: int, threshold: Optional[int] = None) -> NotificationReminder:
    """
    Creates a new notification reminder.

    Args:
        db (Session): The database session.
        reminder_type (ReminderType): The type of reminder.
        expires_at (datetime): The expiration time of the reminder.
        user_id (int): The ID of the user associated with the reminder.
        threshold (Optional[int]): The threshold value to check for (e.g., days left or usage percent).

    Returns:
        NotificationReminder: The newly created NotificationReminder object.
    """
    reminder = NotificationReminder(type=reminder_type, expires_at=expires_at, user_id=user_id)
    if threshold is not None:
        reminder.threshold = threshold
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def get_notification_reminder(
        db: Session, user_id: int, reminder_type: ReminderType, threshold: Optional[int] = None
) -> Union[NotificationReminder, None]:
    """
    Retrieves a notification reminder for a user.

    Args:
        db (Session): The database session.
        user_id (int): The ID of the user.
        reminder_type (ReminderType): The type of reminder to retrieve.
        threshold (Optional[int]): The threshold value to check for (e.g., days left or usage percent).

    Returns:
        Union[NotificationReminder, None]: The NotificationReminder object if found and not expired, None otherwise.
    """
    query = db.query(NotificationReminder).filter(
        NotificationReminder.user_id == user_id,
        NotificationReminder.type == reminder_type
    )

    # If a threshold is provided, filter for reminders with this threshold
    if threshold is not None:
        query = query.filter(NotificationReminder.threshold == threshold)

    reminder = query.first()

    if reminder is None:
        return None

    # Check if the reminder has expired
    if reminder.expires_at and reminder.expires_at < datetime.utcnow():
        db.delete(reminder)
        db.commit()
        return None

    return reminder


def delete_notification_reminder_by_type(
        db: Session, user_id: int, reminder_type: ReminderType, threshold: Optional[int] = None
) -> None:
    """
    Deletes a notification reminder for a user based on the reminder type and optional threshold.

    Args:
        db (Session): The database session.
        user_id (int): The ID of the user.
        reminder_type (ReminderType): The type of reminder to delete.
        threshold (Optional[int]): The threshold to delete (e.g., days left or usage percent). If not provided, deletes all reminders of that type.
    """
    stmt = delete(NotificationReminder).where(
        NotificationReminder.user_id == user_id,
        NotificationReminder.type == reminder_type
    )

    # If a threshold is provided, include it in the filter
    if threshold is not None:
        stmt = stmt.where(NotificationReminder.threshold == threshold)

    db.execute(stmt)
    db.commit()


def delete_notification_reminder(db: Session, dbreminder: NotificationReminder) -> None:
    """
    Deletes a specific notification reminder.

    Args:
        db (Session): The database session.
        dbreminder (NotificationReminder): The NotificationReminder object to delete.
    """
    db.delete(dbreminder)
    db.commit()
    return


def verify_portal_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate an end-user for the self-service portal."""
    from app.models.admin import pwd_context

    dbuser = get_user(db, username)
    if not dbuser or not dbuser.portal_enabled or not dbuser.hashed_portal_password:
        return None
    if pwd_context.verify(password, dbuser.hashed_portal_password):
        return dbuser
    return None


def list_user_orders(db: Session, user_id: int, limit: int = 20) -> List[UserOrder]:
    return (
        db.query(UserOrder)
        .filter(UserOrder.user_id == user_id)
        .order_by(UserOrder.created_at.desc())
        .limit(limit)
        .all()
    )


def list_usernames_by_stat(
    db: Session, category: str, admin: Admin = None, limit: int = 15
):
    """Return ``(usernames, total)`` for a dashboard stat category so the UI can
    show a hover preview. ``category`` is one of: ``total``, ``online``, or any
    :class:`UserStatus` value (active/disabled/expired/limited/on_hold).
    ``usernames`` is capped at ``limit``; ``total`` is the full count."""
    from config import ONLINE_WINDOW_MINUTES

    query = db.query(User.username, User.online_at)
    if admin:
        query = query.filter(User.admin == admin)

    if category == "online":
        cutoff = datetime.utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
        query = query.filter(
            User.online_at.isnot(None),
            User.online_at >= cutoff,
            User.status.in_((UserStatus.active, UserStatus.on_hold)),
        ).order_by(User.online_at.desc())
    elif category == "total":
        query = query.order_by(User.username.asc())
    else:
        try:
            status = UserStatus(category)
        except ValueError:
            return [], 0
        query = query.filter(User.status == status).order_by(User.username.asc())

    total = query.count()
    usernames = [row[0] for row in query.limit(max(1, limit)).all()]
    return usernames, total


def count_online_users(db: Session, minutes: int = None, admin: Admin = None):
    """Count users online *now*: those whose ``online_at`` falls within the last
    ``minutes`` (defaults to ``ONLINE_WINDOW_MINUTES``). ``online_at`` is bumped
    both by real traffic (5s usage job) and by subscription refresh. Only
    billable statuses (active / on_hold) are counted."""
    from config import ONLINE_WINDOW_MINUTES

    window = ONLINE_WINDOW_MINUTES if minutes is None else minutes
    cutoff = datetime.utcnow() - timedelta(minutes=window)
    query = db.query(func.count(User.id)).filter(
        User.online_at.isnot(None),
        User.online_at >= cutoff,
        User.status.in_((UserStatus.active, UserStatus.on_hold)),
    )
    if admin:
        query = query.filter(User.admin == admin)
    return query.scalar()


# --- Subscription endpoints & token aliases ---


def list_subscription_endpoints(db: Session, *, enabled_only: bool = False) -> List[SubscriptionEndpoint]:
    q = db.query(SubscriptionEndpoint).order_by(SubscriptionEndpoint.id.asc())
    if enabled_only:
        q = q.filter(SubscriptionEndpoint.enabled.is_(True))
    return q.all()


def get_subscription_endpoint(db: Session, endpoint_id: int) -> Optional[SubscriptionEndpoint]:
    return db.query(SubscriptionEndpoint).filter(SubscriptionEndpoint.id == endpoint_id).first()


def get_subscription_endpoint_by_slug(db: Session, slug: str) -> Optional[SubscriptionEndpoint]:
    return db.query(SubscriptionEndpoint).filter(SubscriptionEndpoint.slug == slug).first()


def get_subscription_endpoint_by_inbound_tag(
    db: Session, inbound_tag: str
) -> Optional[SubscriptionEndpoint]:
    """Explicit per-inbound override (``export_mode=inbound_only``, one row per tag)."""
    if not inbound_tag:
        return None
    return (
        db.query(SubscriptionEndpoint)
        .filter(SubscriptionEndpoint.inbound_tag == inbound_tag)
        .first()
    )


def get_subscription_endpoint_by_host_path(
    db: Session,
    host: Optional[str],
    path_prefix: str,
    *,
    enabled_only: bool = True,
) -> Optional[SubscriptionEndpoint]:
    prefix = (path_prefix or "").strip().strip("/")
    if not prefix:
        return None
    q = db.query(SubscriptionEndpoint).filter(SubscriptionEndpoint.path_prefix == prefix)
    if enabled_only:
        q = q.filter(SubscriptionEndpoint.enabled.is_(True))
    if host:
        q = q.filter(SubscriptionEndpoint.host == host.strip().lower().split(":")[0])
    else:
        q = q.filter(SubscriptionEndpoint.host.is_(None))
    return q.first()


def upsert_subscription_endpoint(db: Session, data: dict) -> tuple[SubscriptionEndpoint, bool]:
    """Insert or update by slug, then by ``(host, path_prefix)``.

    Returns ``(endpoint, created)``. When host/path already exists under another
    slug, the existing row is updated in place and its slug is kept.
    """
    slug = data.get("slug")
    if not slug:
        raise ValueError("slug is required")

    ep = get_subscription_endpoint_by_slug(db, slug)
    if ep:
        return update_subscription_endpoint(db, ep, data), False

    path_prefix = data.get("path_prefix")
    if path_prefix:
        ep = get_subscription_endpoint_by_host_path(
            db, data.get("host"), path_prefix, enabled_only=False
        )
        if ep:
            merge = dict(data)
            if ep.slug != slug:
                merge.pop("slug", None)
            return update_subscription_endpoint(db, ep, merge), False

    return create_subscription_endpoint(db, data), True


def get_default_subscription_endpoint(db: Session) -> Optional[SubscriptionEndpoint]:
    ep = get_subscription_endpoint_by_slug(db, "default")
    if ep:
        return ep
    return (
        db.query(SubscriptionEndpoint)
        .filter(SubscriptionEndpoint.enabled.is_(True))
        .order_by(SubscriptionEndpoint.id.asc())
        .first()
    )


def create_subscription_endpoint(db: Session, data: dict) -> SubscriptionEndpoint:
    ep = SubscriptionEndpoint(**data)
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep


def update_subscription_endpoint(
    db: Session, ep: SubscriptionEndpoint, data: dict
) -> SubscriptionEndpoint:
    for key, val in data.items():
        if val is not None or key in ("host", "inbound_tag", "listen_port", "format_default", "legacy_panel_id"):
            setattr(ep, key, val)
    db.commit()
    db.refresh(ep)
    return ep


def remove_subscription_endpoint(db: Session, ep: SubscriptionEndpoint) -> None:
    db.delete(ep)
    db.commit()


def get_subscription_token_alias(
    db: Session,
    token: str,
    *,
    endpoint_id: Optional[int] = None,
) -> Optional[SubscriptionTokenAlias]:
    """Resolve legacy subId — always scoped by endpoint when host is known (panel.md §10)."""
    if not token:
        return None
    q = db.query(SubscriptionTokenAlias).filter(SubscriptionTokenAlias.token == token)
    if endpoint_id is not None:
        return q.filter(SubscriptionTokenAlias.endpoint_id == endpoint_id).first()
    return q.filter(SubscriptionTokenAlias.endpoint_id.is_(None)).first()


def get_subscription_token_alias_any_endpoint(
    db: Session,
    token: str,
) -> Optional[SubscriptionTokenAlias]:
    """Resolve a legacy subId across any endpoint (reseller branding hosts)."""
    if not token:
        return None
    return (
        db.query(SubscriptionTokenAlias)
        .filter(SubscriptionTokenAlias.token == token)
        .order_by(SubscriptionTokenAlias.id.asc())
        .first()
    )


def create_subscription_token_alias(
    db: Session, data: dict, *, commit: bool = True
) -> SubscriptionTokenAlias:
    alias = SubscriptionTokenAlias(**data)
    db.add(alias)
    if commit:
        db.commit()
        db.refresh(alias)
    else:
        db.flush()
    return alias


def upsert_subscription_token_alias(
    db: Session,
    *,
    token: str,
    user_id: int,
    endpoint_id: Optional[int] = None,
    source: str = "manual",
    commit: bool = True,
) -> SubscriptionTokenAlias:
    existing = get_subscription_token_alias(db, token, endpoint_id=endpoint_id)
    if existing:
        existing.user_id = user_id
        existing.source = source
        if commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing
    return create_subscription_token_alias(
        db,
        {
            "token": token,
            "user_id": user_id,
            "endpoint_id": endpoint_id,
            "source": source,
        },
        commit=commit,
    )


def list_subscription_token_aliases_for_user(
    db: Session, user_id: int
) -> List[SubscriptionTokenAlias]:
    return (
        db.query(SubscriptionTokenAlias)
        .filter(SubscriptionTokenAlias.user_id == user_id)
        .order_by(SubscriptionTokenAlias.id.asc())
        .all()
    )
