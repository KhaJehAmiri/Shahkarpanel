from collections import defaultdict
from datetime import datetime
from operator import attrgetter
from typing import Optional, Union
import time

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
            except SAOperationalError as err:
                db.rollback()
                text = f"{getattr(err, 'orig', None) or err}".lower()
                if tries < 5 and (
                    "deadlock" in text
                    or "could not serialize" in text
                    or "statement timeout" in text
                    or "querycanceled" in text
                ):
                    tries += 1
                    time.sleep(0.05 * tries)
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
    with GetDB() as db:
        try:
            from app.db.usage_upsert import upsert_protocol_usage

            upsert_protocol_usage(
                db, params, node_id, created_at, protocol, consumption_factor
            )
            return
        except Exception:
            db.rollback()
        proto = str(protocol)[:32]
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
        try:
            from app.db.usage_upsert import upsert_node_user_usage

            upsert_node_user_usage(db, params, node_id, created_at, consumption_factor)
            return
        except Exception:
            db.rollback()
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


# Cumulative Xray user>>>email totals (reset=False). Advancing the baseline
# before a successful DB bill permanently drops VLESS/etc bytes on timeout.
from app.usage_baselines import CumulativeByteTracker

_xray_usage_tracker = CumulativeByteTracker()


def get_users_stats(api: XRayAPI):
    """Return per-user *cumulative* counters, or ``None`` when the API failed.

    Distinguishing failure from a genuine empty interval lets the collector
    refresh a stale gRPC channel / fall back to RPyC loopback stats instead of
    silently dropping traffic. Callers must convert cumulatives to deltas via
    ``_xray_usage_tracker`` and only commit baselines after a successful bill.
    """
    if api is None:
        return None
    try:
        params = defaultdict(int)
        up_params = defaultdict(int)
        down_params = defaultdict(int)
        # reset=False: never zero node counters before DB bill succeeds.
        for stat in filter(attrgetter('value'), api.get_users_stats(reset=False, timeout=4)):
            uid = stat.name.split('.', 1)[0]
            try:
                int(uid)
            except (TypeError, ValueError):
                continue
            params[uid] += stat.value
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


def _cumulative_params_to_deltas(node_id, params: list) -> tuple:
    """Convert cumulative ``{"uid","value",...}`` rows into interval deltas."""
    if not params:
        return [], None
    totals = {str(p["uid"]): int(p.get("value") or 0) for p in params}
    up_map = {str(p["uid"]): int(p.get("up") or 0) for p in params}
    down_map = {str(p["uid"]): int(p.get("down") or 0) for p in params}
    deltas, pending = _xray_usage_tracker.peek_from_totals(node_id, totals)
    out = []
    for uid, value in deltas.items():
        # Preserve up/down proportion from the cumulative split when possible.
        up_c = up_map.get(uid, 0)
        down_c = down_map.get(uid, 0)
        total_c = up_c + down_c
        if total_c > 0 and value > 0:
            up = int(value * up_c / total_c)
            down = value - up
        else:
            up, down = 0, value
        out.append({"uid": uid, "value": value, "up": up, "down": down})
    return out, pending


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


def _collect_node_users_stats(
    node_id, api: XRayAPI, node=None, *, pending_out: Optional[list] = None
) -> list:
    """gRPC stats with stale-channel refresh + RPyC loopback fallback.

    Returns *interval* deltas. Cumulative baselines are appended to
    ``pending_out`` and must be committed after a successful DB bill.
    """
    params = get_users_stats(api)
    if params is None and node is not None and hasattr(node, "ensure_api"):
        try:
            if node.ensure_api(refresh=True, allow_unstarted=True, timeout=5):
                params = get_users_stats(getattr(node, "_api", None))
        except Exception as exc:
            logger.warning("get_users_stats refresh failed for node %s: %s", node_id, exc)

    if params is None and node is not None:
        try:
            remote = getattr(node, "remote", None)
            if remote is not None and hasattr(remote, "xray_users_transfer"):
                # reset=False — never wipe counters before DB bill.
                raw = remote.xray_users_transfer(False)
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                if isinstance(raw, str):
                    import json

                    transfer = json.loads(raw or "{}")
                else:
                    transfer = dict(raw or {})
                params = _params_from_xray_transfer(transfer)
        except AttributeError:
            params = None
        except Exception as exc:
            msg = str(exc)
            if "RPyC busy" in msg or "skipped fast call" in msg:
                logger.debug(
                    "xray_users_transfer fallback skipped (busy) for node %s", node_id
                )
            else:
                logger.warning(
                    "xray_users_transfer fallback failed for node %s: %s", node_id, exc
                )
            params = None

    if not params:
        return []

    deltas, pending = _cumulative_params_to_deltas(node_id, params)
    if pending is not None and pending_out is not None:
        pending_out.append(pending)
    return deltas


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
        xray_pending: list = []
        params = _collect_node_users_stats(
            node_id, api, node, pending_out=xray_pending
        )
    except Exception as exc:
        logger.warning("flush_node_user_stats node %s failed: %s", node_id, exc)
        return 0
    if not params:
        return 0
    coefficient = {node_id: float(getattr(node, "usage_coefficient", 1) or 1)}
    record_aggregated_user_usages({node_id: params}, coefficient)
    for item in xray_pending:
        _xray_usage_tracker.commit_pending(item)
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
        try:
            from sqlalchemy import text

            db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
        except Exception:
            pass
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

    # record users usage (only active / on_hold — disabled users must not accrue traffic).
    # Do NOT write ``online_at`` here: presence + ``bump_users_online_at`` own that
    # column. Concurrent per-row traffic UPDATEs + bulk online_at UPDATEs deadlocked
    # on ``users`` (different lock order) and aborted billing ticks.
    newly_limited: list = []
    with GetDB() as db:
        try:
            from sqlalchemy import text

            db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
        except Exception:
            pass
        if users_usage:
            users_usage = sorted(users_usage, key=lambda p: int(p["uid"]))
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
                )
            # Chunk to shrink row-lock windows (full-fleet executemany was
            # hitting statement_timeout and dropping already-collected bytes).
            chunk = 80
            for i in range(0, len(users_usage), chunk):
                safe_execute(db, stmt, users_usage[i:i + chunk])

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
            split_rows = sorted(split_rows, key=lambda p: int(p["uid"]))
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


def _readopt_stats_channel(node_id, node, *, timeout: float = 2.0) -> bool:
    """Re-attach the gRPC stats client to a core that is up but unadopted.

    A failed ``restart()`` (Finalmask Xray-WG flip, connect backoff) leaves
    ``started=False``/``_api=None`` while the node's Xray keeps serving users.
    The collector then skipped the node with no log at all, so every byte on
    it — VLESS included — went unbilled and ``online_at`` never advanced.
    """
    if not (getattr(node, "has_live_rpyc", None) and node.has_live_rpyc()):
        return False
    try:
        adopted = node.ensure_api(
            refresh=True, allow_unstarted=True, timeout=max(0.5, float(timeout))
        )
    except Exception as exc:
        logger.warning("xray stats re-adopt for node %s failed: %s", node_id, exc)
        return False
    if not adopted:
        logger.warning("xray stats channel unavailable for node %s", node_id)
        return False
    node.started = True
    logger.warning("xray stats channel re-adopted for node %s", node_id)
    return True


def _collect_user_usage_params_body(*, deadline: float, progress: dict | None = None) -> tuple:
    """Inner collect; skips later sources once ``deadline`` is reached."""

    def _remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def _publish(api_params, usage_coefficient, protocol_breakdown):
        if progress is not None:
            progress["r"] = (api_params, usage_coefficient, list(protocol_breakdown))

    def _timed_out(where: str) -> bool:
        if time.monotonic() < deadline:
            return False
        logger.warning("usage collect deadline hit after %s", where)
        return True

    try:
        from app.wireguard.finalmask_usage import finalmask_node_ids

        fm_ids = finalmask_node_ids()
    except Exception:
        fm_ids = set()

    api_instances = {None: xray.api}
    usage_coefficient = {None: 1}
    node_refs: dict = {None: None}

    # Cap serial re-adopt attempts: each ensure_api used to cost up to 5s, and
    # N failed nodes made collect exceed the 5s usage interval forever
    # (max_instances=1 → every tick skipped).
    for node_id, node in list(xray.nodes.items()):
        if node_id in fm_ids:
            # Authoritative Finalmask path is collect_finalmask_usage_params().
            continue
        # Use lock-free has_live_api — node.connected pings RPyC under a lock
        # shared with WG/health jobs and was freezing Overview stats.
        # No ensure_api re-adopt on the hot 5s path (hung adopt burned the
        # whole interval before map_rpc). Health/reconcile re-adopts offline.
        if getattr(node, "has_live_api", None) and node.has_live_api():
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient
            node_refs[node_id] = node
        elif getattr(node, "started", False) and getattr(node, "_api", None) is not None:
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient
            node_refs[node_id] = node

    from app.utils.concurrency import map_rpc
    import threading

    xray_pending: list = []
    _xray_pend_lock = threading.Lock()

    def _one(nid, api):
        local: list = []
        result = _collect_node_users_stats(
            nid, api, node_refs.get(nid), pending_out=local
        ) or []
        if local:
            with _xray_pend_lock:
                xray_pending.extend(local)
        return result

    rpc_timeout = min(1.8, max(0.4, _remaining()))
    api_params = map_rpc(_one, api_instances, timeout=rpc_timeout, default=[])
    if progress is not None and xray_pending:
        progress.setdefault("xray_pending", []).extend(xray_pending)
    _publish(api_params, usage_coefficient, [])

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
    try:
        proto_map = _node_usage_protocols(api_instances.keys())
    except Exception:
        logger.debug("protocol map lookup failed", exc_info=True)
        proto_map = {}
    for node_id, params in api_params.items():
        proto = proto_map.get(node_id, "xray")
        _add_breakdown(proto, node_id, params, usage_coefficient.get(node_id, 1))
    _publish(api_params, usage_coefficient, protocol_breakdown)

    if _timed_out("xray"):
        return api_params, usage_coefficient, protocol_breakdown

    # Secondary collectors in parallel so no protocol is starved when the 5s
    # budget is tight (sequential order used to skip sing-box / WG entirely).
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _collect_singbox():
        from app.singbox.usage import collect_singbox_usage_params

        return ("singbox",) + collect_singbox_usage_params()

    def _collect_finalmask():
        from app.wireguard.finalmask_usage import collect_finalmask_usage_params

        return ("finalmask",) + collect_finalmask_usage_params()

    def _collect_wg():
        from app.wireguard.usage import collect_wg_usage_params

        return ("wg",) + collect_wg_usage_params()

    def _collect_panel_wg():
        from app.wireguard.usage import collect_panel_host_wg_usage_params

        return ("panel_wg",) + collect_panel_host_wg_usage_params()

    secondary_budget = max(0.5, _remaining())
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="usage-proto") as pool:
        futures = [
            pool.submit(_collect_singbox),
            pool.submit(_collect_finalmask),
            pool.submit(_collect_wg),
            pool.submit(_collect_panel_wg),
        ]
        try:
            for fut in as_completed(futures, timeout=secondary_budget):
                try:
                    kind, params, coef, pend = fut.result()
                except (ConnectionError, TimeoutError, OSError) as exc:
                    logger.warning("secondary usage collector failed: %s", exc)
                    continue
                except Exception:
                    logger.exception("secondary usage collector failed")
                    continue
                if progress is not None and pend:
                    key = {
                        "singbox": "singbox_pending",
                        "finalmask": "finalmask_pending",
                        "wg": "wg_pending",
                        "panel_wg": "panel_wg_pending",
                    }.get(kind)
                    if key:
                        progress.setdefault(key, []).extend(pend)
                if kind == "singbox":
                    from app.singbox.usage import merge_singbox_usage

                    for node_id, rows in params.items():
                        _add_breakdown(
                            "singbox", node_id, rows, coef.get(node_id, 1)
                        )
                    merge_singbox_usage(api_params, usage_coefficient, params, coef)
                else:
                    from app.wireguard.finalmask_usage import merge_finalmask_usage
                    from app.wireguard.usage import merge_wg_usage

                    for node_id, rows in params.items():
                        _add_breakdown(
                            "wireguard", node_id, rows, coef.get(node_id, 1)
                        )
                    if kind == "finalmask":
                        merge_finalmask_usage(
                            api_params, usage_coefficient, params, coef
                        )
                    else:
                        merge_wg_usage(api_params, usage_coefficient, params, coef)
                _publish(api_params, usage_coefficient, protocol_breakdown)
        except TimeoutError:
            logger.warning(
                "usage collect deadline during secondary protocols (%.1fs)",
                secondary_budget,
            )
            for fut in futures:
                fut.cancel()

    _timed_out("secondary")
    return api_params, usage_coefficient, protocol_breakdown


def collect_user_usage_params() -> tuple:
    """Gather raw per-user stats from the local Xray core and every connected
    node.  Returns ``(api_params, usage_coefficient, protocol_breakdown)``.

    Hard-capped to the usage-job interval so a hung Finalmask/WG/sing-box
    path cannot pin ``max_instances=1`` and freeze the 5s cadence.
    """
    import threading

    budget = max(2.5, float(JOB_RECORD_USER_USAGES_INTERVAL) - 0.8)
    box: dict = {}
    errors: list = []

    def _run():
        try:
            box["r"] = _collect_user_usage_params_body(
                deadline=time.monotonic() + budget,
                progress=box,
            )
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=_run, name="usage-collect", daemon=True)
    t.start()
    t.join(budget + 0.25)

    def _pack():
        result = box.get("r") or ({None: []}, {None: 1}, [])
        pending = {
            "singbox": list(box.get("singbox_pending") or []),
            "finalmask": list(box.get("finalmask_pending") or []),
            "wg": list(box.get("wg_pending") or []),
            "panel_wg": list(box.get("panel_wg_pending") or []),
            "xray": list(box.get("xray_pending") or []),
        }
        return result[0], result[1], result[2], pending

    if "r" in box:
        return _pack()
    if t.is_alive():
        logger.warning(
            "collect_user_usage_params hard-timeout after %.1fs — waiting briefly for partial",
            budget,
        )
        t.join(0.75)
    if "r" in box:
        return _pack()
    if errors:
        raise errors[0]
    logger.warning("collect_user_usage_params returned empty after timeout")
    return {None: []}, {None: 1}, [], {
        "singbox": [],
        "finalmask": [],
        "wg": [],
        "panel_wg": [],
        "xray": [],
    }


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


_USAGE_TICK_LOCK = None  # threading.Lock, created lazily
_USAGE_BILL_LOCK = None


def record_user_usages():
    """Scheduler entry: return immediately; at most one collect in flight.

    Collect holds a short lock; billing runs after the lock is released so a
    slow upsert cannot block the next 5s tick.
    """
    import threading

    global _USAGE_TICK_LOCK, _USAGE_BILL_LOCK
    if _USAGE_TICK_LOCK is None:
        _USAGE_TICK_LOCK = threading.Lock()
    if _USAGE_BILL_LOCK is None:
        _USAGE_BILL_LOCK = threading.Lock()

    if not _USAGE_TICK_LOCK.acquire(blocking=False):
        logger.debug("record_user_usages: previous collect still running — skip")
        return

    started = time.monotonic()

    def _run():
        payload = None
        try:
            payload = _collect_usage_tick_payload()
        except Exception:
            logger.exception("record_user_usages collect failed")
        finally:
            _USAGE_TICK_LOCK.release()

        if payload is None:
            return

        # Bill off-thread so a slow upsert never piles up collect runners.
        def _bill():
            try:
                _bill_usage_tick_payload(payload)
                logger.info(
                    "record_user_usages finished in %.1fs",
                    time.monotonic() - started,
                )
            except Exception:
                logger.exception("record_user_usages billing failed")

        threading.Thread(target=_bill, name="usage-bill", daemon=True).start()

    threading.Thread(target=_run, name="record-user-usages", daemon=True).start()


def _collect_usage_tick_payload():
    """Collect-only phase (holds the usage tick lock)."""
    try:
        from app.presence import note_usage_tick

        note_usage_tick()
    except Exception:
        pass
    api_params, usage_coefficient, protocol_breakdown, pending = (
        collect_user_usage_params()
    )
    return api_params, usage_coefficient, protocol_breakdown, pending


def _commit_all_usage_pending(pending: dict) -> None:
    """Advance cumulative baselines only after a successful DB bill."""
    if not pending:
        return
    sb = pending.get("singbox") or []
    if sb:
        from app.singbox.usage import commit_singbox_pending

        commit_singbox_pending(sb)
    fm = pending.get("finalmask") or []
    if fm:
        from app.wireguard.finalmask_usage import commit_finalmask_pending

        commit_finalmask_pending(fm)
    wg = pending.get("wg") or []
    if wg:
        from app.wireguard.usage import commit_wg_pending

        commit_wg_pending(wg)
    host = pending.get("panel_wg") or []
    if host:
        from app.wireguard.usage import commit_panel_host_wg_pending

        commit_panel_host_wg_pending(host)
    xr = pending.get("xray") or []
    for item in xr:
        _xray_usage_tracker.commit_pending(item)


def _bill_usage_tick_payload(payload):
    """Bill phase — runs outside the collect lock; serialized billing."""
    import threading

    global _USAGE_BILL_LOCK
    if _USAGE_BILL_LOCK is None:
        _USAGE_BILL_LOCK = threading.Lock()

    # Blocking is fine here: collect lock is already released, so the next
    # 5s collect can proceed while we wait for the previous upsert to finish.
    with _USAGE_BILL_LOCK:
        api_params, usage_coefficient, protocol_breakdown, pending = payload
        uids = {int(p["uid"]) for params in api_params.values() for p in params}
        try:
            bump_users_online_at(uids)
        except Exception:
            logger.exception("online_at bump failed")
        billable_ids: set = set()
        with GetDB() as db:
            try:
                from sqlalchemy import text

                db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
            except Exception:
                pass
            if uids:
                billable_ids = {
                    row[0]
                    for row in db.query(User.id)
                    .filter(User.id.in_(uids), User.status.in_(BILLABLE_STATUSES))
                    .all()
                }
        try:
            record_aggregated_user_usages(api_params, usage_coefficient)
            record_overage_usages(api_params, usage_coefficient)
            if billable_ids:
                record_protocol_breakdown(protocol_breakdown, billable_ids)
        except Exception:
            # Leave all cumulative baselines uncommitted so the next tick re-bills.
            raise
        else:
            _commit_all_usage_pending(pending)


def record_node_usages():
    api_instances = {None: xray.api}
    for node_id, node in list(xray.nodes.items()):
        if getattr(node, "has_live_api", None) and node.has_live_api():
            api_instances[node_id] = node.api
        elif getattr(node, "started", False) and getattr(node, "_api", None) is not None:
            api_instances[node_id] = node.api

    from app.utils.concurrency import map_rpc

    def _one(nid, api):
        try:
            return get_outbounds_stats(api) or []
        except Exception as exc:
            logger.warning("get_outbounds_stats timed out/failed for node %s: %s", nid, exc)
            return []

    api_params = map_rpc(_one, api_instances, timeout=8, default=[])

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
