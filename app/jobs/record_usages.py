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
    """Return per-user params, or ``None`` when the API call itself failed.

    Distinguishing failure from a genuine empty interval lets the collector
    refresh a stale gRPC channel / fall back to RPyC loopback stats instead of
    silently dropping Finalmask WireGuard traffic.
    """
    if api is None:
        return None
    try:
        params = defaultdict(int)
        up_params = defaultdict(int)
        down_params = defaultdict(int)
        # Keep timeout short so one hung node cannot pin the usage job
        # (max_instances=1) long enough for Overview online_users to hit 0.
        for stat in filter(attrgetter('value'), api.get_users_stats(reset=True, timeout=4)):
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
        return None


def bump_users_online_at(uids) -> int:
    """Set ``online_at=now`` for billable users. Returns rows touched.

    The authoritative writer is the presence tracker's own thread
    (``app.presence``); this job only adds the users it happened to bill this
    tick, so the counter never depends on billing I/O completing.
    """
    from app.presence import mark_online

    return mark_online(uids)


def _params_from_xray_transfer(transfer: dict) -> list:
    """Convert ``{email: {rx, tx}}`` (RPyC loopback) into usage-job params."""
    out = []
    for email, counters in (transfer or {}).items():
        try:
            uid = str(email).split(".", 1)[0]
            int(uid)
        except (TypeError, ValueError):
            continue
        try:
            down = int((counters or {}).get("rx") or 0)
            up = int((counters or {}).get("tx") or 0)
        except (TypeError, ValueError):
            continue
        value = up + down
        if value <= 0:
            continue
        out.append({"uid": uid, "value": value, "up": up, "down": down})
    return out


def _collect_node_users_stats(node_id, api: XRayAPI, node=None) -> list:
    """gRPC stats with stale-channel refresh + RPyC loopback fallback."""
    params = get_users_stats(api)
    if params is not None:
        return params

    if node is not None and hasattr(node, "ensure_api"):
        try:
            if node.ensure_api(refresh=True, timeout=5):
                params = get_users_stats(node.api)
                if params is not None:
                    return params
        except Exception as exc:
            logger.warning("get_users_stats refresh failed for node %s: %s", node_id, exc)

    if node is None:
        return []
    try:
        remote = getattr(node, "remote", None)
        if remote is None or not hasattr(remote, "xray_users_transfer"):
            return []
        raw = remote.xray_users_transfer(True)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            import json

            transfer = json.loads(raw or "{}")
        else:
            transfer = dict(raw or {})
        return _params_from_xray_transfer(transfer)
    except AttributeError:
        return []
    except Exception as exc:
        logger.warning("xray_users_transfer fallback failed for node %s: %s", node_id, exc)
        return []


def flush_node_user_stats(node_id: int) -> int:
    """Pull+record one node's user stats before a dataplane mutation.

    Finalmask ``rmi``/restart wipes unread Xray counters; calling this first
    keeps WireGuard billing from leaking those bytes. Returns bytes recorded.
    """
    node = xray.nodes.get(node_id)
    if node is None:
        return 0
    try:
        if hasattr(node, "ensure_api"):
            node.ensure_api(timeout=5)
    except Exception:
        pass
    api = getattr(node, "_api", None)
    try:
        params = _collect_node_users_stats(node_id, api, node)
    except Exception as exc:
        logger.warning("flush_node_user_stats node %s failed: %s", node_id, exc)
        return 0
    if not params:
        return 0
    coefficient = {node_id: float(getattr(node, "usage_coefficient", 1) or 1)}
    record_aggregated_user_usages({node_id: params}, coefficient)
    try:
        uids = {int(p["uid"]) for p in params}
        with GetDB() as db:
            billable_ids = {
                row[0]
                for row in db.query(User.id)
                .filter(User.id.in_(uids), User.status.in_(BILLABLE_STATUSES))
                .all()
            }
        proto_map = _node_usage_protocols([node_id])
        record_protocol_breakdown(
            [{
                "protocol": proto_map.get(node_id, "xray"),
                "node_id": node_id,
                "params": params,
                "coefficient": coefficient[node_id],
            }],
            billable_ids,
        )
    except Exception:
        logger.debug("flush_node_user_stats protocol breakdown skipped", exc_info=True)
    return sum(int(p.get("value") or 0) for p in params)


def get_outbounds_stats(api: XRayAPI):
    if api is None:
        return []
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

    # PAYG / prepaid burn only for volume-capped accounts. Unlimited accounts
    # (monthly wholesale tariffs, etc.) are charged at create/renew — their
    # bytes must not inflate Admin.users_usage or they get double-billed.
    data_limit_by_uid = {int(row[0]): row[2] for row in billable_rows}

    def _payg_billable(uid: int) -> bool:
        dl = data_limit_by_uid.get(int(uid))
        try:
            return dl is not None and int(dl) > 0
        except (TypeError, ValueError):
            return False

    admin_usage = defaultdict(int)
    for user_usage in users_usage:
        uid = int(user_usage["uid"])
        admin_id = user_admin_map.get(uid)
        if admin_id and _payg_billable(uid):
            admin_usage[admin_id] += user_usage["value"]

    # record users usage (only active / on_hold — disabled users must not accrue traffic or online_at)
    newly_limited: list = []
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
        # single batched pass *after* this session closes. Holding the DB
        # transaction open while disconnecting nodes caused idle-in-transaction
        # stalls and blocked the 5s usage job (max_instances=1 → Overview stats freeze).
        for uid in hit_limit_uids:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser and limit_user_quota(db, dbuser, cap_usage=True, disconnect=False):
                newly_limited.append(int(dbuser.id))

        admin_data = [{"admin_id": admin_id, "value": value} for admin_id, value in admin_usage.items()]
        if admin_data:
            admin_update_stmt = update(Admin). \
                where(Admin.id == bindparam('admin_id')). \
                values(users_usage=Admin.users_usage + bindparam('value'))
            safe_execute(db, admin_update_stmt, admin_data)

    if newly_limited:
        try:
            from types import SimpleNamespace

            from app.quota import disconnect_users_everywhere

            with GetDB() as db:
                rows = (
                    db.query(User.id, User.username)
                    .filter(User.id.in_(newly_limited))
                    .all()
                )
            # Network I/O must run after the billing session closes.
            disconnect_users_everywhere(
                [SimpleNamespace(id=int(uid), username=username) for uid, username in rows]
            )
        except Exception:
            logger.exception("batched quota disconnect failed for %s users", len(newly_limited))

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


def _connected_node_core_kinds(node_ids) -> dict:
    """Map ``node_id -> core_kind`` (``"xray"``/``"wireguard"``) for the given nodes.

    Used only for the informational protocol breakdown. Best-effort — an
    empty/failed lookup falls back to ``xray``.
    """
    ids = [nid for nid in node_ids if nid is not None]
    if not ids:
        return {}
    try:
        from app.db.models import Node

        with GetDB() as db:
            rows = db.query(Node.id, Node.core_kind).filter(Node.id.in_(ids)).all()
        return {r[0]: (str(r[1]) if r[1] is not None else "xray") for r in rows}
    except Exception:
        logger.debug("core_kind lookup for protocol breakdown failed", exc_info=True)
        return {}


def _node_usage_protocols(node_ids) -> dict:
    """Map ``node_id -> protocol label`` for Xray API stats breakdown.

    Tunnel/exit nodes also use ``core_kind=wireguard`` for agent packaging, but
    their per-user stats are VLESS/Xray — only Finalmask relays
    (``xray_wg_enabled``) should be labelled ``wireguard``.
    """
    ids = [nid for nid in node_ids if nid is not None]
    if not ids:
        return {}
    try:
        from app.db.models import NodeWireGuard

        with GetDB() as db:
            rows = (
                db.query(NodeWireGuard.node_id, NodeWireGuard.xray_wg_enabled)
                .filter(NodeWireGuard.node_id.in_(ids))
                .all()
            )
        enabled = {int(r[0]): bool(r[1]) for r in rows}
        return {
            nid: ("wireguard" if enabled.get(nid) else "xray")
            for nid in ids
        }
    except Exception:
        logger.debug("xray_wg protocol lookup failed", exc_info=True)
        kinds = _connected_node_core_kinds(ids)
        return {
            nid: ("wireguard" if kinds.get(nid) == "wireguard" else "xray")
            for nid in ids
        }


def collect_user_usage_params() -> tuple:
    """Gather raw per-user stats from the local Xray core and every connected
    node.  Returns ``(api_params, usage_coefficient, protocol_breakdown)``.

    ``api_params`` is the *merged* per-node/user shape that feeds the single
    authoritative ``User.used_traffic``. ``protocol_breakdown`` is a separate
    list of per-source contributions — ``{"protocol", "node_id", "params",
    "coefficient"}`` — captured *before* merging so a node that serves several
    protocols (e.g. a WireGuard-core node that also runs sing-box) is attributed
    correctly instead of collapsing to one per-node label.

    Finalmask relays are billed only via ``finalmask_usage`` (cumulative /
    delta over RPyC). They are excluded from ``get_users_stats(reset=True)``
    so a flaky TLS API cannot wipe unread WireGuard counters.
    """
    try:
        from app.wireguard.finalmask_usage import finalmask_node_ids

        fm_ids = finalmask_node_ids()
    except Exception:
        fm_ids = set()

    api_instances = {None: xray.api}
    usage_coefficient = {None: 1}
    node_refs: dict = {None: None}

    for node_id, node in list(xray.nodes.items()):
        if node_id in fm_ids:
            # Authoritative Finalmask path is collect_finalmask_usage_params().
            continue
        # Use lock-free has_live_api — node.connected pings RPyC under a lock
        # shared with WG/health jobs and was freezing Overview stats.
        if getattr(node, "has_live_api", None) and node.has_live_api():
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient
            node_refs[node_id] = node
        elif getattr(node, "started", False) and getattr(node, "_api", None) is not None:
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient
            node_refs[node_id] = node

    # Do NOT use ``with ThreadPoolExecutor``: after ``future.result(timeout=…)``
    # the context manager still ``shutdown(wait=True)``, so one hung node RPC
    # blocks the whole 5s usage job forever (max_instances=1 → Overview freeze).
    executor = ThreadPoolExecutor(max_workers=10)
    api_params: dict = {}
    try:
        futures = {
            node_id: executor.submit(
                _collect_node_users_stats,
                node_id,
                api,
                node_refs.get(node_id),
            )
            for node_id, api in api_instances.items()
        }
        for node_id, future in futures.items():
            try:
                api_params[node_id] = future.result(timeout=12) or []
            except Exception as exc:
                logger.warning("get_users_stats timed out/failed for node %s: %s", node_id, exc)
                api_params[node_id] = []
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    protocol_breakdown: list[dict] = []

    def _add_breakdown(protocol, node_id, params, coefficient):
        # Snapshot the list: the merge_* helpers below ``.extend()`` the shared
        # ``api_params[node_id]`` list in place, which would otherwise leak
        # another protocol's rows into this contribution.
        if params:
            protocol_breakdown.append(
                {
                    "protocol": protocol,
                    "node_id": node_id,
                    "params": list(params),
                    "coefficient": coefficient,
                }
            )

    # Non-Finalmask Xray API stats (tunnel exits, panel core, …).
    proto_map = _node_usage_protocols(api_instances.keys())
    for node_id, params in api_params.items():
        proto = proto_map.get(node_id, "xray")
        _add_breakdown(proto, node_id, params, usage_coefficient.get(node_id, 1))

    # Finalmask: cumulative user>>>email over RPyC (never reset-on-read).
    try:
        from app.wireguard.finalmask_usage import (
            collect_finalmask_usage_params,
            merge_finalmask_usage,
        )

        fm_params, fm_coefficient = collect_finalmask_usage_params()
        for node_id, params in fm_params.items():
            _add_breakdown("wireguard", node_id, params, fm_coefficient.get(node_id, 1))
        merge_finalmask_usage(api_params, usage_coefficient, fm_params, fm_coefficient)
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.warning("Finalmask usage collection skipped: %s", exc)
    except Exception:
        logger.exception("Finalmask usage collection failed")

    try:
        from app.wireguard.usage import collect_wg_usage_params, merge_wg_usage

        wg_params, wg_coefficient = collect_wg_usage_params()
        for node_id, params in wg_params.items():
            _add_breakdown("wireguard", node_id, params, wg_coefficient.get(node_id, 1))
        merge_wg_usage(api_params, usage_coefficient, wg_params, wg_coefficient)
    except Exception:
        pass

    # Panel-host WireGuard exit: when the panel itself terminates tunneled WG,
    # user traffic exits via the panel host's kernel wg0 (not any node), so its
    # per-peer counters must be collected here or that traffic is never billed
    # and online_at never advances (Overview / online-user freeze).
    try:
        from app.wireguard.usage import (
            collect_panel_host_wg_usage_params,
            merge_wg_usage,
        )

        host_params, host_coefficient = collect_panel_host_wg_usage_params()
        for node_id, params in host_params.items():
            _add_breakdown("wireguard", node_id, params, host_coefficient.get(node_id, 1))
        merge_wg_usage(api_params, usage_coefficient, host_params, host_coefficient)
    except Exception:
        logger.debug("panel-host WG usage collection skipped", exc_info=True)

    try:
        from app.singbox.usage import collect_singbox_usage_params, merge_singbox_usage

        sb_params, sb_coefficient = collect_singbox_usage_params()
        for node_id, params in sb_params.items():
            _add_breakdown("singbox", node_id, params, sb_coefficient.get(node_id, 1))
        merge_singbox_usage(api_params, usage_coefficient, sb_params, sb_coefficient)
    except Exception:
        pass

    return api_params, usage_coefficient, protocol_breakdown


def record_protocol_breakdown(
    protocol_breakdown: list,
    billable_ids: set,
):
    if DISABLE_RECORDING_NODE_USAGE:
        return
    for entry in protocol_breakdown:
        filtered = [p for p in entry["params"] if int(p["uid"]) in billable_ids]
        if filtered:
            record_user_protocol_stats(
                filtered, entry["node_id"], entry["protocol"], entry["coefficient"]
            )


def record_user_usages():
    api_params, usage_coefficient, protocol_breakdown = collect_user_usage_params()
    uids = {int(p["uid"]) for params in api_params.values() for p in params}
    # Presence first, before any billing write can stall this tick. This is a
    # secondary source: app.presence keeps online_at fresh on its own thread.
    try:
        bump_users_online_at(uids)
    except Exception:
        logger.exception("online_at bump failed")
    if uids:
        from app.quota import enforce_disconnect_for_non_billable

        # Pass db=None so the enforce helper opens a short query session and
        # never holds a transaction across hot-disconnect / core-restart I/O.
        enforce_disconnect_for_non_billable(None, uids)
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
        record_protocol_breakdown(protocol_breakdown, billable_ids)

    # Live 1-device exclusivity (WG vs VLESS/sing-box) — after traffic commit.
    try:
        from app.utils.device_exclusivity import enforce_device_exclusivity

        enforce_device_exclusivity(protocol_breakdown, candidate_uids=uids or None)
    except Exception:
        logger.exception("device exclusivity enforcement failed")

    # Concurrent device cap from live Xray online IPs (not subscription import).
    try:
        from app.utils.device_limit import enforce_live_device_limits

        enforce_live_device_limits(uids or None)
    except Exception:
        logger.exception("live device limit enforcement failed")

    from app.billing_guard import check_billing_integrity

    check_billing_integrity(xray)


def record_node_usages():
    api_instances = {None: xray.api}
    for node_id, node in list(xray.nodes.items()):
        if getattr(node, "has_live_api", None) and node.has_live_api():
            api_instances[node_id] = node.api
        elif getattr(node, "started", False) and getattr(node, "_api", None) is not None:
            api_instances[node_id] = node.api

    executor = ThreadPoolExecutor(max_workers=10)
    api_params: dict = {}
    try:
        futures = {node_id: executor.submit(get_outbounds_stats, api) for node_id, api in api_instances.items()}
        for node_id, future in futures.items():
            try:
                api_params[node_id] = future.result(timeout=20)
            except Exception as exc:
                logger.warning("get_outbounds_stats timed out/failed for node %s: %s", node_id, exc)
                api_params[node_id] = []
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

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
# online_at is refreshed by app.presence on a dedicated thread — deliberately
# not a scheduler job, so a pool starved by hung node RPCs cannot zero the
# Overview online counter.
