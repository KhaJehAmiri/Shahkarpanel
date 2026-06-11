"""
Functions for managing proxy hosts, users, user templates, nodes, and administrative tasks.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import and_, delete, func, or_
from sqlalchemy.orm import Query, Session, joinedload
from sqlalchemy.sql.functions import coalesce

from app.db.models import (
    JWT,
    TLS,
    Admin,
    AdminUsageLogs,
    NextPlan,
    Node,
    NodeGroup,
    NodeUsage,
    NodeUserUsage,
    NodeSingBox,
    NodeWireGuard,
    NotificationReminder,
    Plan,
    Proxy,
    ProxyHost,
    ProxyInbound,
    ProxyTypes,
    System,
    User,
    UserOrder,
    UserTemplate,
    UserUsageResetLogs,
)
from app.models.admin import AdminCreate, AdminModify, AdminPartialModify
from app.models.node import CoreKind, NodeCreate, NodeModify, NodeStatus, NodeUsageResponse
from app.models.proxy import ProxyHost as ProxyHostModify
from app.models.user import (
    ReminderType,
    UserCreate,
    UserDataLimitResetStrategy,
    UserModify,
    UserResponse,
    UserStatus,
    UserUsageResponse,
)
from app.models.user_template import UserTemplateCreate, UserTemplateModify, NATIVE_TEMPLATE_PROTOCOLS, native_template_marker
from app.utils.helpers import calculate_expiration_days, calculate_usage_percent
from config import NOTIFY_DAYS_LEFT, NOTIFY_REACHED_USAGE_PERCENT, USERS_AUTODELETE_DAYS


def add_default_host(db: Session, inbound: ProxyInbound):
    """
    Adds a default host to a proxy inbound.

    Args:
        db (Session): Database session.
        inbound (ProxyInbound): Proxy inbound to add the default host to.
    """
    host = ProxyHost(remark="Nexus ({USERNAME}) [{PROTOCOL} - {TRANSPORT}]", address="{SERVER_IP}", inbound=inbound)
    db.add(host)
    db.commit()


def get_or_create_inbound(db: Session, inbound_tag: str) -> ProxyInbound:
    """
    Retrieves or creates a proxy inbound based on the given tag.

    Args:
        db (Session): Database session.
        inbound_tag (str): The tag of the inbound.

    Returns:
        ProxyInbound: The retrieved or newly created proxy inbound.
    """
    inbound = db.query(ProxyInbound).filter(ProxyInbound.tag == inbound_tag).first()
    if not inbound:
        inbound = ProxyInbound(tag=inbound_tag)
        db.add(inbound)
        db.commit()
        add_default_host(db, inbound)
        db.refresh(inbound)
    return inbound


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
    return inbound.hosts


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
    inbound.hosts.append(
        ProxyHost(
            remark=host.remark,
            address=host.address,
            port=host.port,
            path=host.path,
            sni=host.sni,
            host=host.host,
            inbound=inbound,
            security=host.security,
            alpn=host.alpn,
            fingerprint=host.fingerprint
        )
    )
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
    inbound.hosts = [
        ProxyHost(
            remark=host.remark,
            address=host.address,
            port=host.port,
            path=host.path,
            sni=host.sni,
            host=host.host,
            inbound=inbound,
            security=host.security,
            alpn=host.alpn,
            fingerprint=host.fingerprint,
            allowinsecure=host.allowinsecure,
            is_disabled=host.is_disabled,
            mux_enable=host.mux_enable,
            fragment_setting=host.fragment_setting,
            noise_setting=host.noise_setting,
            random_user_agent=host.random_user_agent,
            use_sni_as_host=host.use_sni_as_host,
        ) for host in modified_hosts
    ]
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
    return db.query(User).options(joinedload(User.admin)).options(joinedload(User.next_plan))


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


UsersSortingOptions = Enum('UsersSortingOptions', {
    'username': User.username.asc(),
    'used_traffic': User.used_traffic.asc(),
    'data_limit': User.data_limit.asc(),
    'expire': User.expire.asc(),
    'created_at': User.created_at.asc(),
    '-username': User.username.desc(),
    '-used_traffic': User.used_traffic.desc(),
    '-data_limit': User.data_limit.desc(),
    '-expire': User.expire.desc(),
    '-created_at': User.created_at.desc(),
})


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

    if search:
        query = query.filter(or_(User.username.ilike(f"%{search}%"), User.note.ilike(f"%{search}%")))

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

    if return_with_count:
        count = query.count()

    if sort:
        query = query.order_by(*(opt.value for opt in sort))

    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    if return_with_count:
        return query.all(), count

    return query.all()


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


def create_user(db: Session, user: UserCreate, admin: Admin = None) -> User:
    """
    Creates a new user with provided details.

    Args:
        db (Session): Database session.
        user (UserCreate): User creation details.
        admin (Admin, optional): Admin associated with the user.

    Returns:
        User: The created user object.
    """
    if admin is not None and admin.max_users is not None:
        current = get_users_count(db, admin=admin)
        if current >= admin.max_users:
            raise ValueError(f"Reseller user limit reached ({admin.max_users})")

    excluded_inbounds_tags = user.excluded_inbounds
    proxies = []
    for proxy_type, settings in user.proxies.items():
        excluded_inbounds = [
            get_or_create_inbound(db, tag) for tag in excluded_inbounds_tags[proxy_type]
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
    db.commit()
    db.refresh(dbuser)
    if user.portal_enabled or user.portal_password:
        from app.client.provision import ensure_app_proxies

        ensure_app_proxies(db, dbuser)
        db.refresh(dbuser)
    return dbuser


def remove_user(db: Session, dbuser: User) -> User:
    """
    Removes a user from the database.

    Args:
        db (Session): Database session.
        dbuser (User): The user object to be removed.

    Returns:
        User: The removed user object.
    """
    db.delete(dbuser)
    db.commit()
    return dbuser


def remove_users(db: Session, dbusers: List[User]):
    """
    Removes multiple users from the database.

    Args:
        db (Session): Database session.
        dbusers (List[User]): List of user objects to be removed.
    """
    for dbuser in dbusers:
        db.delete(dbuser)
    db.commit()
    return


def update_user(db: Session, dbuser: User, modify: UserModify) -> User:
    """
    Updates a user with new details.

    Args:
        db (Session): Database session.
        dbuser (User): The user object to be updated.
        modify (UserModify): New details for the user.

    Returns:
        User: The updated user object.
    """
    from app.models.proxy import apply_proxy_patch

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
                dbproxy.excluded_inbounds = [get_or_create_inbound(db, tag) for tag in tags]

    explicit_status = modify.status
    if explicit_status is not None:
        dbuser.status = explicit_status
        if explicit_status in (UserStatus.disabled, UserStatus.expired, UserStatus.limited):
            dbuser.online_at = None
        dbuser.last_status_change = datetime.utcnow()

    if modify.data_limit is not None:
        dbuser.data_limit = (modify.data_limit or None)
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

    if explicit_status is not None:
        dbuser.status = explicit_status
        if explicit_status in (UserStatus.disabled, UserStatus.expired, UserStatus.limited):
            dbuser.online_at = None

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

    db.commit()
    db.refresh(dbuser)
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
    dbuser.expire = dbuser.next_plan.expire

    dbuser.used_traffic = 0
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
    for attr in ("role", "max_users", "max_total_traffic", "max_nodes", "commission_percent"):
        value = getattr(modified_admin, attr, None)
        if value is not None:
            setattr(dbadmin, attr, value)

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

    Args:
        db (Session): The database session.
        dbnode (Node): The Node object to be removed.

    Returns:
        Node: The removed Node object.
    """
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
        dbnode.address = modify.address

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


def set_node_wg_stack(
    db: Session,
    dbnode: Node,
    *,
    plain_enabled: Optional[bool] = None,
    awg_enabled: Optional[bool] = None,
) -> "NodeWireGuard":
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if plain_enabled is not None:
        cfg.plain_enabled = plain_enabled
    if awg_enabled is not None:
        cfg.awg_enabled = awg_enabled
        if awg_enabled:
            ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
            if cfg.awg_jc is None:
                from app.wireguard.awg import random_awg_preset
                for field, value in random_awg_preset().items():
                    setattr(cfg, field, value)
    if not cfg.plain_enabled and not cfg.awg_enabled:
        raise ValueError("At least one of plain WireGuard or AmneziaWG must stay enabled")
    db.commit()
    db.refresh(cfg)
    return cfg


def set_node_wireguard(db: Session, dbnode: Node, *, interface: str = "wg0",
                       listen_port: int = 51820, subnet: str = "10.10.0.0/24",
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
    "awg_jc", "awg_jmin", "awg_jmax", "awg_s1", "awg_s2",
    "awg_h1", "awg_h2", "awg_h3", "awg_h4",
)


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
    """Return nodes whose core_kind is 'wireguard'."""
    query = db.query(Node).filter(Node.core_kind == CoreKind.wireguard.value)
    if enabled_only:
        query = query.filter(Node.status != NodeStatus.disabled)
    return query.all()


def get_singbox_nodes(db: Session, enabled_only: bool = True) -> List[Node]:
    """Return nodes that carry a sing-box config (Hysteria2/TUIC).

    Unlike WireGuard (a dedicated core_kind), sing-box runs *alongside* Xray on
    a normal node, so membership is defined by the presence of a NodeSingBox
    row with at least one protocol enabled.
    """
    query = db.query(Node).join(NodeSingBox, NodeSingBox.node_id == Node.id)
    if enabled_only:
        query = query.filter(
            Node.status != NodeStatus.disabled,
            or_(NodeSingBox.hysteria2_enabled.is_(True), NodeSingBox.tuic_enabled.is_(True)),
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


def remove_plan(db: Session, plan: Plan) -> None:
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
    dbnode.xray_version = version
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


def count_online_users(db: Session, hours: int = 24, admin: Admin = None):
    """Users seen on VPN recently; only billable statuses (active / on_hold)."""
    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=hours)
    query = db.query(func.count(User.id)).filter(
        User.online_at.isnot(None),
        User.online_at >= twenty_four_hours_ago,
        User.status.in_((UserStatus.active, UserStatus.on_hold)),
    )
    if admin:
        query = query.filter(User.admin == admin)
    return query.scalar()
