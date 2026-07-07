from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from operator import attrgetter
from typing import Union

from pymysql.err import OperationalError
from sqlalchemy import and_, bindparam, case, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError as SAOperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app import scheduler, xray, logger
from app.db import GetDB, crud
from app.db.models import Admin, NodeUserProtocolUsage, NodeUsage, NodeUserUsage, System, User
from app.models.user import UserStatus
from app.quota import clamp_usage_entries, limit_user_quota
from config import (
    DISABLE_RECORDING_NODE_USAGE,
    JOB_RECORD_NODE_USAGES_INTERVAL,
    JOB_RECORD_USER_USAGES_INTERVAL,
)
from xray_api import XRay as XRayAPI
from xray_api import exc as xray_exc


def safe_execute(db: Session, stmt, params=None):
    if db.bind.name == 'mysql':
        if isinstance(stmt, Insert):
            stmt = stmt.prefix_with('IGNORE')

        tries = 0
        done = False
        while not done:
            try:
                db.connection().execute(stmt, params)
                db.commit()
                done = True
            except OperationalError as err:
                if err.args[0] == 1213 and tries < 3:  # Deadlock
                    db.rollback()
                    tries += 1
                    continue
                raise err

    elif db.bind.name == 'postgresql':
        # PostgreSQL has no "INSERT IGNORE"; rows are de-duplicated by the
        # caller's pre-check, so a concurrent duplicate raises IntegrityError.
        # We swallow it for inserts (matching MySQL's IGNORE semantics) and
        # retry on serialization/deadlock failures.
        tries = 0
        while True:
            try:
                db.connection().execute(stmt, params)
                db.commit()
                return
            except IntegrityError:
                db.rollback()
                if isinstance(stmt, Insert):
                    return
                raise
            except SAOperationalError:
                db.rollback()
                if tries < 3:
                    tries += 1
                    continue
                raise

    else:
        db.connection().execute(stmt, params)
        db.commit()


def record_user_protocol_stats(
    params: list,
    node_id: Union[int, None],
    protocol: str,
    consumption_factor: int = 1,
):
    """Best-effort per-protocol hourly breakdown (informational only)."""
    if not params or not protocol:
        return

    created_at = datetime.fromisoformat(datetime.utcnow().strftime("%Y-%m-%dT%H:00:00"))
    proto = str(protocol)[:32]

    with GetDB() as db:
        select_stmt = select(NodeUserProtocolUsage.user_id).where(
            and_(
                NodeUserProtocolUsage.node_id == node_id,
                NodeUserProtocolUsage.created_at == created_at,
                NodeUserProtocolUsage.protocol == proto,
            )
        )
        existings = {r[0] for r in db.execute(select_stmt).fetchall()}
        to_insert = []
        for p in params:
            uid = int(p["uid"])
            if uid in existings:
                continue
            to_insert.append(
                {
                    "uid": uid,
                    "created_at": created_at,
                    "node_id": node_id,
                    "protocol": proto,
                    "used_traffic": 0,
                }
            )
        if to_insert:
            stmt = insert(NodeUserProtocolUsage).values(
                user_id=bindparam("uid"),
                created_at=bindparam("created_at"),
                node_id=bindparam("node_id"),
                protocol=bindparam("protocol"),
                used_traffic=0,
            )
            safe_execute(db, stmt, to_insert)

        stmt = (
            update(NodeUserProtocolUsage)
            .values(
                used_traffic=NodeUserProtocolUsage.used_traffic
                + bindparam("value") * consumption_factor
            )
            .where(
                and_(
                    NodeUserProtocolUsage.user_id == bindparam("uid"),
                    NodeUserProtocolUsage.node_id == node_id,
                    NodeUserProtocolUsage.created_at == created_at,
                    NodeUserProtocolUsage.protocol == proto,
                )
            )
        )
        safe_execute(db, stmt, params)


def record_user_stats(params: list, node_id: Union[int, None],
                      consumption_factor: int = 1):
    if not params:
        return

    created_at = datetime.fromisoformat(datetime.utcnow().strftime('%Y-%m-%dT%H:00:00'))

    with GetDB() as db:
        # make user usage row if doesn't exist
        select_stmt = select(NodeUserUsage.user_id) \
            .where(and_(NodeUserUsage.node_id == node_id, NodeUserUsage.created_at == created_at))
        existings = [r[0] for r in db.execute(select_stmt).fetchall()]
        uids_to_insert = set()

        for p in params:
            uid = int(p['uid'])
            if uid in existings:
                continue
            uids_to_insert.add(uid)

        if uids_to_insert:
            stmt = insert(NodeUserUsage).values(
                user_id=bindparam('uid'),
                created_at=created_at,
                node_id=node_id,
                used_traffic=0
            )
            safe_execute(db, stmt, [{'uid': uid} for uid in uids_to_insert])

        # record
        stmt = update(NodeUserUsage) \
            .values(used_traffic=NodeUserUsage.used_traffic + bindparam('value') * consumption_factor) \
            .where(and_(NodeUserUsage.user_id == bindparam('uid'),
                        NodeUserUsage.node_id == node_id,
                        NodeUserUsage.created_at == created_at))
        safe_execute(db, stmt, params)


def record_node_stats(params: dict, node_id: Union[int, None]):
    if not params:
        return

    created_at = datetime.fromisoformat(datetime.utcnow().strftime('%Y-%m-%dT%H:00:00'))

    with GetDB() as db:

        # make node usage row if doesn't exist
        select_stmt = select(NodeUsage.node_id). \
            where(and_(NodeUsage.node_id == node_id, NodeUsage.created_at == created_at))
        notfound = db.execute(select_stmt).first() is None
        if notfound:
            stmt = insert(NodeUsage).values(created_at=created_at, node_id=node_id, uplink=0, downlink=0)
            safe_execute(db, stmt)

        # record
        stmt = update(NodeUsage). \
            values(uplink=NodeUsage.uplink + bindparam('up'), downlink=NodeUsage.downlink + bindparam('down')). \
            where(and_(NodeUsage.node_id == node_id, NodeUsage.created_at == created_at))

        safe_execute(db, stmt, params)


def get_users_stats(api: XRayAPI):
    try:
        params = defaultdict(int)
        up_params = defaultdict(int)
        down_params = defaultdict(int)
        for stat in filter(attrgetter('value'), api.get_users_stats(reset=True, timeout=30)):
            uid = stat.name.split('.', 1)[0]
            params[uid] += stat.value
            # Preserve the up/down split (Xray reports uplink/downlink per user)
            # so the subscription header can show real upload/download.
            link = getattr(stat, "link", None)
            if link == "uplink":
                up_params[uid] += stat.value
            elif link == "downlink":
                down_params[uid] += stat.value
        params = list(
            {
                "uid": uid,
                "value": value,
                "up": up_params.get(uid, 0),
                "down": down_params.get(uid, 0),
            }
            for uid, value in params.items()
        )
        return params
    except xray_exc.XrayError as exc:
        logger.warning("get_users_stats failed: %s", exc)
        return []


def get_outbounds_stats(api: XRayAPI):
    try:
        params = [{"up": stat.value, "down": 0} if stat.link == "uplink" else {"up": 0, "down": stat.value}
                  for stat in filter(attrgetter('value'), api.get_outbounds_stats(reset=True, timeout=10))]
        return params
    except xray_exc.XrayError:
        return []


# Statuses whose traffic is billed against ``User.used_traffic``.  Disabled /
# limited / expired users must never accrue traffic or have ``online_at`` bumped.
BILLABLE_STATUSES = (UserStatus.active, UserStatus.on_hold)


def aggregate_user_usage(api_params: dict, usage_coefficient: dict) -> list:
    """Sum per-user stats across every source (Xray cores, nodes, WireGuard)
    applying each source's usage coefficient.

    ``api_params`` maps ``node_id -> [{"uid": <User.id>, "value": <bytes>}, ...]``
    and is the single shape every collector (Xray ``get_users_stats`` and the
    WireGuard transfer collector) must emit so that one ``User.used_traffic``
    stays authoritative across all protocols.  ``uid`` must resolve to an
    integer ``User.id``.
    """
    users_usage = defaultdict(int)
    for node_id, params in api_params.items():
        coefficient = usage_coefficient.get(node_id, 1)
        for param in params:
            users_usage[param['uid']] += int(param['value'] * coefficient)
    return [{"uid": uid, "value": value} for uid, value in users_usage.items()]


def aggregate_user_split(api_params: dict, usage_coefficient: dict) -> tuple:
    """Aggregate per-user upload/download bytes across every source.

    Returns ``(ups, downs)`` mapping ``uid -> bytes``. Collectors that don't
    report a split (WireGuard / sing-box emit a combined ``value``) are counted
    as download. Purely informational — never used for quota enforcement.
    """
    ups = defaultdict(int)
    downs = defaultdict(int)
    for node_id, params in api_params.items():
        coefficient = usage_coefficient.get(node_id, 1)
        for param in params:
            up = int(param.get("up", 0) * coefficient)
            down = int(param.get("down", 0) * coefficient)
            if not up and not down:
                down = int(param.get("value", 0) * coefficient)
            ups[param["uid"]] += up
            downs[param["uid"]] += down
    return ups, downs


def record_overage_usages(api_params: dict, usage_coefficient: dict) -> None:
    """Accumulate bytes used while non-billable (post-quota) into ``overage_traffic``."""
    users_usage = aggregate_user_usage(api_params, usage_coefficient)
    if not users_usage:
        return

    with GetDB() as db:
        uids = [int(u["uid"]) for u in users_usage]
        overage_ids = {
            row[0]
            for row in db.query(User.id)
            .filter(User.id.in_(uids), User.status.notin_(BILLABLE_STATUSES))
            .all()
        }

    overage_usage = [
        u for u in users_usage
        if int(u["uid"]) in overage_ids and int(u["value"]) > 0
    ]
    if not overage_usage:
        return

    with GetDB() as db:
        stmt = (
            update(User)
            .where(User.id == bindparam("uid"))
            .values(overage_traffic=User.overage_traffic + bindparam("value"))
        )
        safe_execute(db, stmt, overage_usage)


def record_aggregated_user_usages(api_params: dict, usage_coefficient: dict):
    """Apply aggregated per-user usage to the central counters.

    Single source of truth for billing: every protocol feeds the same
    ``api_params`` shape, gets merged here, filtered to billable statuses, and
    written once to ``User.used_traffic`` (plus ``Admin.users_usage`` and the
    hourly ``NodeUserUsage`` breakdown).  Extracted from ``record_user_usages``
    so it is unit-testable and so WireGuard usage can be injected without a
    second DB write path.
    """
    users_usage = aggregate_user_usage(api_params, usage_coefficient)
    if not users_usage:
        return

    with GetDB() as db:
        uids = [int(u["uid"]) for u in users_usage]
        billable_rows = (
            db.query(User.id, User.used_traffic, User.data_limit, User.admin_id)
            .filter(User.id.in_(uids), User.status.in_(BILLABLE_STATUSES))
            .all()
        )
        billable_ids = {row[0] for row in billable_rows}
        user_admin_map = {row[0]: row[3] for row in billable_rows}

    users_usage = [u for u in users_usage if int(u["uid"]) in billable_ids]
    if not users_usage:
        return

    usage_rows = [(r[0], r[1], r[2]) for r in billable_rows]
    users_usage, hit_limit_uids = clamp_usage_entries(users_usage, usage_rows)
    if not users_usage and not hit_limit_uids:
        return

    admin_usage = defaultdict(int)
    for user_usage in users_usage:
        admin_id = user_admin_map.get(int(user_usage["uid"]))
        if admin_id:
            admin_usage[admin_id] += user_usage["value"]

    # record users usage (only active / on_hold — disabled users must not accrue traffic or online_at)
    with GetDB() as db:
        if users_usage:
            stmt = update(User). \
                where(User.id == bindparam('uid')). \
                values(
                    used_traffic=case(
                        (and_(
                            User.data_limit.isnot(None),
                            User.data_limit > 0,
                            User.used_traffic + bindparam('value') > User.data_limit,
                        ), User.data_limit),
                        else_=User.used_traffic + bindparam('value'),
                    ),
                    online_at=datetime.utcnow(),
                )
            safe_execute(db, stmt, users_usage)

            billed_uids = [int(u["uid"]) for u in users_usage]
            hit_limit_uids = [
                row[0]
                for row in db.query(User.id)
                .filter(
                    User.id.in_(billed_uids),
                    User.data_limit.isnot(None),
                    User.data_limit > 0,
                    User.used_traffic >= User.data_limit,
                    User.status == UserStatus.active,
                )
                .all()
            ]

        # Move every capped user to ``limited`` first, then drop them all in a
        # single batched pass. Doing the disconnect inline per user meant N users
        # hitting their cap in the same 5s tick triggered N separate disconnect
        # passes back-to-back; one batched call handles the whole set at once.
        newly_limited = []
        for uid in hit_limit_uids:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser and limit_user_quota(db, dbuser, cap_usage=True, disconnect=False):
                newly_limited.append(dbuser)
        if newly_limited:
            from app.quota import disconnect_users_everywhere

            disconnect_users_everywhere(newly_limited)

        admin_data = [{"admin_id": admin_id, "value": value} for admin_id, value in admin_usage.items()]
        if admin_data:
            admin_update_stmt = update(Admin). \
                where(Admin.id == bindparam('admin_id')). \
                values(users_usage=Admin.users_usage + bindparam('value'))
            safe_execute(db, admin_update_stmt, admin_data)

    # Best-effort upload/download split write. Deliberately separate from the
    # authoritative used_traffic path above and wrapped in try/except so a split
    # failure can never disrupt billing.
    try:
        ups, downs = aggregate_user_split(api_params, usage_coefficient)
        split_rows = [
            {"uid": int(uid), "up": ups.get(uid, 0), "down": downs.get(uid, 0)}
            for uid in set(ups) | set(downs)
            if int(uid) in billable_ids and (ups.get(uid, 0) or downs.get(uid, 0))
        ]
        if split_rows:
            with GetDB() as db:
                split_stmt = update(User). \
                    where(User.id == bindparam('uid')). \
                    values(
                        used_traffic_up=User.used_traffic_up + bindparam('up'),
                        used_traffic_down=User.used_traffic_down + bindparam('down'),
                    )
                safe_execute(db, split_stmt, split_rows)
    except Exception:
        logger.debug("up/down split accounting skipped", exc_info=True)

    if DISABLE_RECORDING_NODE_USAGE:
        return

    for node_id, params in api_params.items():
        if params:
            filtered = [p for p in params if int(p["uid"]) in billable_ids]
            record_user_stats(filtered, node_id, usage_coefficient.get(node_id, 1))


def collect_user_usage_params() -> tuple:
    """Gather raw per-user stats from the local Xray core and every connected
    node.  Returns ``(api_params, usage_coefficient, protocol_map)`` where
    ``protocol_map`` maps ``node_id -> protocol label`` for analytics.
    """
    api_instances = {None: xray.api}
    usage_coefficient = {None: 1}
    protocol_map: dict[Union[int, None], str] = {None: "xray"}

    for node_id, node in list(xray.nodes.items()):
        if node.connected and node.started:
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient
            protocol_map[node_id] = "xray"

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {node_id: executor.submit(get_users_stats, api) for node_id, api in api_instances.items()}
    api_params = {node_id: future.result() for node_id, future in futures.items()}

    try:
        from app.wireguard.usage import collect_wg_usage_params, merge_wg_usage

        wg_params, wg_coefficient = collect_wg_usage_params()
        merge_wg_usage(api_params, usage_coefficient, wg_params, wg_coefficient)
        for node_id in wg_params:
            if wg_params.get(node_id):
                protocol_map[node_id] = "wireguard"
    except Exception:
        pass

    try:
        from app.singbox.usage import collect_singbox_usage_params, merge_singbox_usage

        sb_params, sb_coefficient = collect_singbox_usage_params()
        merge_singbox_usage(api_params, usage_coefficient, sb_params, sb_coefficient)
        for node_id in sb_params:
            if sb_params.get(node_id):
                protocol_map[node_id] = "singbox"
    except Exception:
        pass

    return api_params, usage_coefficient, protocol_map


def record_protocol_breakdown(
    api_params: dict,
    usage_coefficient: dict,
    protocol_map: dict,
    billable_ids: set,
):
    if DISABLE_RECORDING_NODE_USAGE:
        return
    for node_id, params in api_params.items():
        if not params:
            continue
        proto = protocol_map.get(node_id, "xray")
        filtered = [p for p in params if int(p["uid"]) in billable_ids]
        if filtered:
            record_user_protocol_stats(
                filtered, node_id, proto, usage_coefficient.get(node_id, 1)
            )


def record_user_usages():
    api_params, usage_coefficient, protocol_map = collect_user_usage_params()
    uids = {int(p["uid"]) for params in api_params.values() for p in params}
    if uids:
        with GetDB() as db:
            from app.quota import enforce_disconnect_for_non_billable

            enforce_disconnect_for_non_billable(db, uids)
    billable_ids: set = set()
    with GetDB() as db:
        uids = {int(p["uid"]) for params in api_params.values() for p in params}
        if uids:
            billable_ids = {
                row[0]
                for row in db.query(User.id)
                .filter(User.id.in_(uids), User.status.in_(BILLABLE_STATUSES))
                .all()
            }
    record_aggregated_user_usages(api_params, usage_coefficient)
    record_overage_usages(api_params, usage_coefficient)
    if billable_ids:
        record_protocol_breakdown(api_params, usage_coefficient, protocol_map, billable_ids)

    from app.billing_guard import check_billing_integrity

    check_billing_integrity(xray)


def record_node_usages():
    api_instances = {None: xray.api}
    for node_id, node in list(xray.nodes.items()):
        if node.connected and node.started:
            api_instances[node_id] = node.api

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {node_id: executor.submit(get_outbounds_stats, api) for node_id, api in api_instances.items()}
    api_params = {node_id: future.result() for node_id, future in futures.items()}

    total_up = 0
    total_down = 0
    for node_id, params in api_params.items():
        for param in params:
            total_up += param['up']
            total_down += param['down']
    if not (total_up or total_down):
        return

    # record nodes usage
    with GetDB() as db:
        stmt = update(System).values(
            uplink=System.uplink + total_up,
            downlink=System.downlink + total_down
        )
        safe_execute(db, stmt)

    if DISABLE_RECORDING_NODE_USAGE:
        return

    for node_id, params in api_params.items():
        record_node_stats(params, node_id)


from app.ha import run_if_leader  # noqa: E402

scheduler.add_job(run_if_leader(record_user_usages), 'interval',
                  seconds=JOB_RECORD_USER_USAGES_INTERVAL,
                  coalesce=True, max_instances=1)
scheduler.add_job(run_if_leader(record_node_usages), 'interval',
                  seconds=JOB_RECORD_NODE_USAGES_INTERVAL,
                  coalesce=True, max_instances=1)
