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

from app import scheduler, xray
from app.db import GetDB, crud
from app.db.models import Admin, NodeUsage, NodeUserUsage, System, User
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
        for stat in filter(attrgetter('value'), api.get_users_stats(reset=True, timeout=30)):
            params[stat.name.split('.', 1)[0]] += stat.value
        params = list({"uid": uid, "value": value} for uid, value in params.items())
        return params
    except xray_exc.XrayError:
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

        for uid in hit_limit_uids:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser:
                limit_user_quota(db, dbuser, cap_usage=True)

        admin_data = [{"admin_id": admin_id, "value": value} for admin_id, value in admin_usage.items()]
        if admin_data:
            admin_update_stmt = update(Admin). \
                where(Admin.id == bindparam('admin_id')). \
                values(users_usage=Admin.users_usage + bindparam('value'))
            safe_execute(db, admin_update_stmt, admin_data)

    if DISABLE_RECORDING_NODE_USAGE:
        return

    for node_id, params in api_params.items():
        if params:
            filtered = [p for p in params if int(p["uid"]) in billable_ids]
            record_user_stats(filtered, node_id, usage_coefficient.get(node_id, 1))


def collect_user_usage_params() -> tuple:
    """Gather raw per-user stats from the local Xray core and every connected
    node.  Returns ``(api_params, usage_coefficient)`` in the shape expected by
    :func:`record_aggregated_user_usages`.

    This is the hook point for additional usage sources: a WireGuard collector
    appends ``node_id -> [{"uid", "value"}]`` entries here so its bytes merge
    into the same central ``User.used_traffic``.
    """
    api_instances = {None: xray.api}
    usage_coefficient = {None: 1}  # default usage coefficient for the main api instance

    for node_id, node in list(xray.nodes.items()):
        if node.connected and node.started:
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient  # fetch the usage coefficient

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {node_id: executor.submit(get_users_stats, api) for node_id, api in api_instances.items()}
    api_params = {node_id: future.result() for node_id, future in futures.items()}

    # Fold native WireGuard usage into the same dicts so it merges into the one
    # central User.used_traffic (no second DB write path). Best-effort: a WG
    # failure must never drop Xray accounting.
    try:
        from app.wireguard.usage import collect_wg_usage_params, merge_wg_usage

        wg_params, wg_coefficient = collect_wg_usage_params()
        merge_wg_usage(api_params, usage_coefficient, wg_params, wg_coefficient)
    except Exception:
        pass

    # Same for sing-box (Hysteria2/TUIC) usage — best-effort fold into the one
    # central User.used_traffic.
    try:
        from app.singbox.usage import collect_singbox_usage_params, merge_singbox_usage

        sb_params, sb_coefficient = collect_singbox_usage_params()
        merge_singbox_usage(api_params, usage_coefficient, sb_params, sb_coefficient)
    except Exception:
        pass

    return api_params, usage_coefficient


def record_user_usages():
    api_params, usage_coefficient = collect_user_usage_params()
    record_aggregated_user_usages(api_params, usage_coefficient)


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
