"""Per-user concurrent device limiting for subscription access."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.db.models import User

logger = logging.getLogger("shahkar-device-limit")

# IPs/fingerprints not seen within this window don't count toward the device limit.
_ACTIVE_WINDOW = timedelta(hours=24)
# Subscribe UI "recent devices" window for fingerprint fallback.
_ONLINE_DISPLAY_WINDOW = timedelta(hours=2)
# How long we remember the last public IP inside a platform bucket (evidence only).
# Lockout decisions do NOT count distinct IPs — Iran CGNAT, Wi‑Fi↔LTE, and
# sub-fetches that go out through an already-up VPN all churn the public IP
# for the *same* phone and were causing false 30‑minute lockouts.
_CONCURRENT_IP_WINDOW = timedelta(minutes=45)
# After a second *platform* (e.g. iPhone + Windows) connects, hide configs.
DEVICE_LOCKOUT_MINUTES = 30

# Live Xray online-count cache (subscribe /info used to block for seconds).
_ONLINE_COUNT_CACHE: dict[int, tuple[float, Optional[int]]] = {}
_ONLINE_COUNT_CACHE_TTL = 15.0
_ONLINE_COUNT_RPC_TIMEOUT = 1  # seconds; grpc Deadline; wall clock capped below
_ONLINE_COUNT_WALL_TIMEOUT = 0.55

_LOCKOUT_UNTIL_KEY = "device_lockout_until"
_LOCKOUT_REASON_KEY = "device_lockout_reason"
_LOCKOUT_EVIDENCE_KEY = "device_lockout_evidence"

_PLATFORM_LABEL_FA = {
    "android": "اندروید",
    "ios": "آیفون / iOS",
    "windows": "ویندوز",
    "macos": "مک",
    "linux": "لینوکس",
    "other": "سایر",
}

_PLATFORM_LABEL_EN = {
    "android": "Android",
    "ios": "iPhone / iOS",
    "windows": "Windows",
    "macos": "Mac",
    "linux": "Linux",
    "other": "Other",
}

# Browser page-views of /subscribe must never consume a device slot — admins and
# users open the link on a PC first, then import on the phone.
_BROWSER_UA_RE = re.compile(r"(Mozilla|Chrome|Safari|Firefox|Edg)/", re.I)
_VPN_CLIENT_UA_RE = re.compile(
    r"v2rayNG|v2rayN|Hiddify|V2[Bb]ox|Happ/|Karing|Clash|Streisand|Shadowrocket|"
    r"Quantumult|Stash|NekoBox|Nekoray|sing-box|FairVPN|Napsternet|Loon|Surge|"
    r"mihomo|FLClash",
    re.I,
)


def _is_browser_ua(user_agent: str = "") -> bool:
    ua = user_agent or ""
    if not _BROWSER_UA_RE.search(ua):
        return False
    if _VPN_CLIENT_UA_RE.search(ua):
        return False
    return True


def _parse_ips(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry_seen(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        seen = value.get("seen")
        return str(seen) if seen else None
    return None


def _prune(ips: dict[str, Any], now: datetime, window: timedelta = _ACTIVE_WINDOW) -> dict[str, Any]:
    cutoff = now - window
    out: dict[str, Any] = {}
    for key, value in ips.items():
        seen_raw = _entry_seen(value)
        if not seen_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(seen_raw))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except ValueError:
            continue
        if ts >= cutoff:
            out[key] = value
    return out


def _infrastructure_ips() -> frozenset[str]:
    """Panel/node addresses must not consume user device slots."""
    now = time.monotonic()
    cached = getattr(_infrastructure_ips, "_cache", None)
    if cached and (now - cached[0]) < 60.0:
        return cached[1]

    from app.utils.system import get_public_ip, get_public_ipv6

    ips = {"127.0.0.1", "::1", "unknown"}
    panel_ip = get_public_ip()
    if panel_ip:
        ips.add(panel_ip)
    panel_v6 = get_public_ipv6()
    if panel_v6:
        ips.add(panel_v6)
    try:
        from app import xray

        for node in xray.nodes.values():
            addr = getattr(node, "address", None)
            if addr:
                ips.add(str(addr))
    except Exception:
        pass
    try:
        from app.db import GetDB
        from app.db.models import Node

        with GetDB() as db:
            for row in db.query(Node.address).all():
                if row[0]:
                    ips.add(str(row[0]))
    except Exception:
        pass
    result = frozenset(ips)
    _infrastructure_ips._cache = (now, result)
    return result


def _is_infrastructure_ip(client_ip: str) -> bool:
    return not client_ip or client_ip in _infrastructure_ips()


def _client_device_entries(ips: dict[str, Any]) -> dict[str, Any]:
    """Drop bare infrastructure IP keys; keep fingerprint keys always."""
    infra = _infrastructure_ips()
    out: dict[str, Any] = {}
    for key, value in ips.items():
        if key.startswith(("fp:", "hw:")):
            out[key] = value
            continue
        if key not in infra:
            out[key] = value
    return out


def classify_client_platform(user_agent: str = "") -> str:
    """Best-effort platform label for device identity (phone vs Windows/desktop)."""
    ua = (user_agent or "").lower()
    # Karing and similar apps advertise `platform/ios` while also listing every
    # core they speak (`NekoBox/Android`, HiddifyNext, …). Trust the explicit
    # hint first so one phone is not split across android+ios buckets.
    hinted = re.search(r"platform/(ios|android|windows|macos|linux|mac)", ua)
    if hinted:
        p = hinted.group(1)
        return "macos" if p in ("macos", "mac") else p
    if re.search(r"android|v2rayng|hiddify.*android|napsternet|surge.*android", ua):
        return "android"
    if re.search(r"iphone|ipad|ios|shadowrocket|stash|quantumult|streisand|hiddify.*ios", ua):
        return "ios"
    # HiddifyNext without OS hint is usually mobile; prefer android over "other".
    if re.search(r"hiddifynext|hiddify", ua) and not re.search(r"windows|macintosh|darwin", ua):
        return "android"
    if re.search(r"windows|v2rayn/|clash.?for.?windows|cfw|nekoray|hiddify.*windows", ua):
        return "windows"
    if re.search(r"macintosh|mac os|darwin", ua):
        return "macos"
    if re.search(r"linux|ubuntu", ua):
        return "linux"
    return "other"


def extract_request_hwid(request) -> str:
    """Pull HWID from common VPN-client headers when present."""
    if request is None:
        return ""
    headers = getattr(request, "headers", None) or {}
    for key in (
        "x-hwid",
        "hwid",
        "x-device-id",
        "x-client-id",
        "x-hiddify-device-id",
    ):
        val = headers.get(key) or headers.get(key.title())
        if val and str(val).strip():
            return str(val).strip()[:128]
    return ""


def device_fingerprint(client_ip: str, user_agent: str = "", hwid: str = "") -> str:
    """Platform bucket key (apps on one OS share a bucket).

    Concurrent device slots are one-per-platform — see
    :func:`count_active_devices`. HWID is display-only (differs per app).
    """
    _ = client_ip, hwid
    return f"plat:{classify_client_platform(user_agent)}"


def _entry_is_active(value: Any, now: datetime, window: timedelta) -> bool:
    """True when a stored fingerprint entry has recent activity."""
    if not isinstance(value, dict):
        ts = _parse_seen_ts(_entry_seen(value))
        return ts is not None and ts >= now - window
    if _entry_recent_ips(value, now, window):
        return True
    ts = _parse_seen_ts(value.get("seen"))
    return ts is not None and ts >= now - window


def _active_platform_slots(
    ips: dict[str, Any],
    now: datetime,
    window: timedelta = _CONCURRENT_IP_WINDOW,
) -> set[str]:
    """Distinct OS buckets with recent subscription activity.

    One iPhone that changes public IP (carrier / VPN-exit sub refresh) still
    counts as a single ``ios`` slot. Phone + Windows → two slots.
    Browser page-view entries (legacy) are ignored.
    """
    slots: set[str] = set()
    for key, value in ips.items():
        if isinstance(value, dict) and _is_browser_ua(str(value.get("ua") or "")):
            continue
        if not _entry_is_active(value, now, window):
            # Legacy bare-IP keys.
            if (
                not key.startswith(("plat:", "fp:", "hw:"))
                and not _is_infrastructure_ip(key)
            ):
                ts = _parse_seen_ts(_entry_seen(value))
                if ts is not None and ts >= now - window:
                    slots.add("other")
            continue
        slots.add(_platform_from_entry(key, value))
    return slots


def _platform_from_entry(key: str, value: Any) -> str:
    if key.startswith("plat:"):
        return key.split(":", 1)[1] or "other"
    if isinstance(value, dict) and value.get("platform"):
        return str(value["platform"])
    return "other"


def _parse_seen_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        return ts
    except ValueError:
        return None


def _entry_recent_ips(value: Any, now: datetime, window: timedelta) -> dict[str, str]:
    """Map of client_ip → seen_iso still inside the concurrent window."""
    if not isinstance(value, dict):
        return {}
    cutoff = now - window
    out: dict[str, str] = {}
    recent = value.get("recent_ips")
    if isinstance(recent, dict):
        for ip, seen in recent.items():
            ip_s = str(ip)
            if _is_infrastructure_ip(ip_s):
                continue
            ts = _parse_seen_ts(seen)
            if ts is not None and ts >= cutoff:
                out[ip_s] = ts.isoformat()
    primary = value.get("ip")
    if primary and not _is_infrastructure_ip(str(primary)):
        ts = _parse_seen_ts(value.get("seen"))
        if ts is not None and ts >= cutoff:
            out.setdefault(str(primary), ts.isoformat())
    return out


def _recent_client_ips(
    ips: dict[str, Any],
    now: datetime,
    window: timedelta = _CONCURRENT_IP_WINDOW,
) -> set[str]:
    found: set[str] = set()
    for key, value in ips.items():
        if isinstance(value, dict):
            found.update(_entry_recent_ips(value, now, window))
        elif key.startswith(("plat:", "fp:", "hw:")):
            continue
        elif not _is_infrastructure_ip(key):
            # Legacy bare-IP map values.
            ts = _parse_seen_ts(_entry_seen(value))
            if ts is not None and ts >= now - window:
                found.add(key)
    return found


def _count_platform_slots(ips: dict[str, Any]) -> int:
    """Fallback when no usable client IPs are stored yet."""
    return len({_platform_from_entry(k, v) for k, v in ips.items()})


def _collapse_same_platform(ips: dict[str, Any], platform: str, keep_key: str) -> dict[str, Any]:
    """Drop legacy per-app keys (hw:/fp:) that belong to the same platform."""
    out: dict[str, Any] = {}
    for key, value in ips.items():
        if key == keep_key:
            out[key] = value
            continue
        if _platform_from_entry(key, value) == platform:
            continue
        out[key] = value
    return out


def _hold_dict(dbuser: User) -> dict[str, Any]:
    raw = getattr(dbuser, "device_conn_hold", None)
    return dict(raw) if isinstance(raw, dict) else {}


def get_device_lockout_remaining(dbuser: User, *, now: Optional[datetime] = None) -> Optional[int]:
    """Seconds left on a device-limit lockout, or None if not locked."""
    hold = _hold_dict(dbuser)
    until_raw = hold.get(_LOCKOUT_UNTIL_KEY)
    if not until_raw:
        return None
    try:
        until = datetime.fromisoformat(str(until_raw))
        if until.tzinfo is not None:
            until = until.replace(tzinfo=None)
    except ValueError:
        return None
    now = now or datetime.utcnow()
    remaining = int((until - now).total_seconds())
    return remaining if remaining > 0 else None


def _app_label_from_ua(user_agent: str = "") -> str:
    ua = (user_agent or "").strip()
    if not ua:
        return ""
    # Prefer first token / known client name for a readable report.
    low = ua.lower()
    for name in (
        "v2rayNG",
        "v2rayN",
        "HiddifyNext",
        "Hiddify",
        "Shadowrocket",
        "Streisand",
        "Stash",
        "Quantumult",
        "NekoBox",
        "Nekoray",
        "Clash",
        "Sing-box",
        "FairVPN",
        "NapsternetV",
    ):
        if name.lower() in low:
            return name
    return ua.split("/")[0].strip()[:40] or ua[:40]


def _fmt_seen_local(iso_raw: Any) -> str:
    ts = _parse_seen_ts(iso_raw)
    if ts is None:
        return "—"
    # Store/display as UTC wall clock; enough for dispute evidence.
    return ts.strftime("%Y-%m-%d %H:%M:%S UTC")


def collect_device_evidence(
    dbuser: User,
    *,
    extra_ip: str = "",
    extra_ua: str = "",
    extra_platform: str = "",
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """One evidence row per platform slot (latest IP/app) — not per IP churn."""
    now = now or datetime.utcnow()
    ips = _client_device_entries(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))
    by_platform: dict[str, dict[str, Any]] = {}

    for key, value in ips.items():
        if not isinstance(value, dict):
            continue
        if not _entry_is_active(value, now, _CONCURRENT_IP_WINDOW):
            continue
        platform = _platform_from_entry(key, value)
        recent = _entry_recent_ips(value, now, _CONCURRENT_IP_WINDOW)
        # Prefer the newest IP inside this bucket (carrier churn is normal).
        if recent:
            ip, seen_iso = max(recent.items(), key=lambda kv: kv[1])
        else:
            ip = str(value.get("ip") or "")
            seen_iso = str(value.get("seen") or now.isoformat())
        if not ip or _is_infrastructure_ip(ip):
            continue
        ua = str(value.get("ua") or "")
        apps = value.get("apps") if isinstance(value.get("apps"), list) else []
        app = _app_label_from_ua(str(apps[-1]) if apps else ua)
        row = {
            "platform": platform,
            "platform_fa": _PLATFORM_LABEL_FA.get(platform, platform),
            "platform_en": _PLATFORM_LABEL_EN.get(platform, platform),
            "ip": ip,
            "app": app,
            "user_agent": (ua or "")[:180],
            "seen_at": seen_iso,
            "seen_at_display": _fmt_seen_local(seen_iso),
        }
        prev = by_platform.get(platform)
        if prev is None or str(row["seen_at"]) >= str(prev.get("seen_at") or ""):
            by_platform[platform] = row

    # Include the triggering client even if we lock before writing its entry.
    extra_ip = (extra_ip or "").strip()
    if extra_ip and not _is_infrastructure_ip(extra_ip):
        plat = (extra_platform or classify_client_platform(extra_ua) or "other").strip()
        row = {
            "platform": plat,
            "platform_fa": _PLATFORM_LABEL_FA.get(plat, plat),
            "platform_en": _PLATFORM_LABEL_EN.get(plat, plat),
            "ip": extra_ip,
            "app": _app_label_from_ua(extra_ua),
            "user_agent": (extra_ua or "")[:180],
            "seen_at": now.isoformat(),
            "seen_at_display": _fmt_seen_local(now.isoformat()),
        }
        prev = by_platform.get(plat)
        if prev is None or str(row["seen_at"]) >= str(prev.get("seen_at") or ""):
            by_platform[plat] = row

    rows = sorted(by_platform.values(), key=lambda r: str(r.get("seen_at") or ""))
    return rows[:12]


def get_device_lockout_evidence(dbuser: User) -> list[dict[str, Any]]:
    hold = _hold_dict(dbuser)
    raw = hold.get(_LOCKOUT_EVIDENCE_KEY)
    if isinstance(raw, list) and raw:
        return [dict(x) for x in raw if isinstance(x, dict)]
    # Fallback: live snapshot if older lockouts lack evidence.
    return collect_device_evidence(dbuser)


def format_device_lockout_report(
    dbuser: User,
    *,
    minutes_left: int,
    evidence: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Short lockout line for VPN profile titles / plain clients.

    The subscribe web UI renders its own compact card + live countdown;
    keep this string brief so apps do not show a wall of text.
    """
    _ = evidence  # structured evidence is returned separately as blocked_devices
    limit = getattr(dbuser, "device_limit", None)
    try:
        cap = max(1, int(limit or 1))
    except (TypeError, ValueError):
        cap = 1
    mins = max(1, int(minutes_left or 1))
    return (
        f"محدودیت دستگاه: بیش از {cap} دستگاه هم‌زمان — "
        f"کانفیگ‌ها حدود {mins} دقیقه مخفی می‌مانند"
    )


def start_device_lockout(
    db: Optional[Session],
    dbuser: User,
    *,
    minutes: int = DEVICE_LOCKOUT_MINUTES,
    reason: str = "device_limit",
    evidence: Optional[list[dict[str, Any]]] = None,
    extra_ip: str = "",
    extra_ua: str = "",
    extra_platform: str = "",
) -> int:
    """Start (or refresh) a subscription config lockout. Returns minutes applied."""
    # Never lock unlimited accounts — stale holds / live probes must not apply.
    raw_limit = getattr(dbuser, "device_limit", None)
    try:
        if raw_limit is None or int(raw_limit) <= 0:
            logger.info(
                "skip device lockout user_id=%s reason=%s (no device_limit)",
                getattr(dbuser, "id", None),
                reason,
            )
            return 0
    except (TypeError, ValueError):
        return 0

    minutes = max(1, int(minutes or DEVICE_LOCKOUT_MINUTES))
    now = datetime.utcnow()
    until = now + timedelta(minutes=minutes)
    hold = _hold_dict(dbuser)
    hold[_LOCKOUT_UNTIL_KEY] = until.isoformat()
    hold[_LOCKOUT_REASON_KEY] = reason
    snap = evidence if evidence is not None else collect_device_evidence(
        dbuser,
        extra_ip=extra_ip,
        extra_ua=extra_ua,
        extra_platform=extra_platform,
        now=now,
    )
    if snap:
        hold[_LOCKOUT_EVIDENCE_KEY] = snap
    dbuser.device_conn_hold = hold
    if db is not None:
        db.commit()
    logger.info(
        "device lockout user_id=%s until=%s reason=%s devices=%s",
        getattr(dbuser, "id", None),
        until.isoformat(),
        reason,
        len(snap or []),
    )
    return minutes


def clear_device_lockout(db: Optional[Session], dbuser: User) -> None:
    hold = _hold_dict(dbuser)
    if (
        _LOCKOUT_UNTIL_KEY not in hold
        and _LOCKOUT_REASON_KEY not in hold
        and _LOCKOUT_EVIDENCE_KEY not in hold
    ):
        return
    hold.pop(_LOCKOUT_UNTIL_KEY, None)
    hold.pop(_LOCKOUT_REASON_KEY, None)
    hold.pop(_LOCKOUT_EVIDENCE_KEY, None)
    dbuser.device_conn_hold = hold or None
    if db is not None:
        db.commit()


def count_active_devices(dbuser: User) -> int:
    """How many device slots count toward the limit (distinct recent platforms)."""
    now = datetime.utcnow()
    ips = _client_device_entries(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))
    slots = _active_platform_slots(ips, now)
    if slots:
        return len(slots)
    return _count_platform_slots(ips)


def account_is_online(dbuser: User, now: Optional[datetime] = None) -> bool:
    """Same live window as the admin dashboard online counter."""
    from config import ONLINE_WINDOW_MINUTES

    online_at = getattr(dbuser, "online_at", None)
    if online_at is None:
        return False
    seen = online_at.replace(tzinfo=None) if online_at.tzinfo is not None else online_at
    now = now or datetime.utcnow()
    return now - seen <= timedelta(minutes=ONLINE_WINDOW_MINUTES)


def _xray_online_device_count(dbuser: User) -> Optional[int]:
    """Live concurrent IPs from Xray ``statsUserOnline`` (panel + nodes).

    Uses the **max** across APIs (not the sum) so the same user seen on one
    exit is not counted once per node.

    Results are cached briefly — subscribe ``/info`` used to fan out sequential
    RPyC calls with a 2s timeout per node and stall the browser for seconds.
    """
    uid = int(getattr(dbuser, "id", 0) or 0)
    now = time.monotonic()
    cached = _ONLINE_COUNT_CACHE.get(uid)
    if cached is not None:
        ts, value = cached
        if now - ts < _ONLINE_COUNT_CACHE_TTL:
            return value

    email = f"{dbuser.id}.{dbuser.username}"
    best = 0
    got_any = False
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app import xray

        apis = []
        if getattr(xray, "api", None) is not None:
            apis.append(xray.api)
        for node in (getattr(xray, "nodes", None) or {}).values():
            api = getattr(node, "api", None)
            if api is not None:
                apis.append(api)
        if not apis:
            _ONLINE_COUNT_CACHE[uid] = (now, None)
            return None

        def _one(api) -> Optional[int]:
            try:
                return int(api.get_user_online_count(email, timeout=_ONLINE_COUNT_RPC_TIMEOUT) or 0)
            except Exception:
                return None

        # Bound wall time: don't wait on every dead node serially.
        pool = ThreadPoolExecutor(max_workers=min(8, len(apis)))
        try:
            futs = [pool.submit(_one, api) for api in apis]
            try:
                for fut in as_completed(futs, timeout=_ONLINE_COUNT_WALL_TIMEOUT):
                    try:
                        n = fut.result()
                    except Exception:
                        continue
                    if n is None:
                        continue
                    got_any = True
                    if n > best:
                        best = n
            except TimeoutError:
                pass
        finally:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)
    except Exception:
        _ONLINE_COUNT_CACHE[uid] = (now, None)
        return None

    result = best if got_any else None
    _ONLINE_COUNT_CACHE[uid] = (now, result)
    # Cap cache size (simple eviction of oldest half).
    if len(_ONLINE_COUNT_CACHE) > 4000:
        oldest = sorted(_ONLINE_COUNT_CACHE.items(), key=lambda kv: kv[1][0])[:2000]
        for k, _ in oldest:
            _ONLINE_COUNT_CACHE.pop(k, None)
    return result


def count_online_devices(dbuser: User, *, live: bool = True) -> int:
    """Devices currently connected for the subscribe overview."""
    now = datetime.utcnow()
    online = account_is_online(dbuser, now)
    if not online:
        return 0

    if live:
        live_n = _xray_online_device_count(dbuser)
        if live_n is not None and live_n > 0:
            return live_n

    entries = _client_device_entries(
        _prune(
            _parse_ips(getattr(dbuser, "device_ips", None)),
            now,
            window=_ONLINE_DISPLAY_WINDOW,
        )
    )
    n = len(entries)
    return max(n, 1)


def record_and_check_device_limit(
    db: Session,
    dbuser: User,
    client_ip: str,
    user_agent: str = "",
    hwid: str = "",
    *,
    enforce: bool = False,
) -> None:
    """Track a platform bucket from a subscription request.

    ``enforce=True`` starts a 30-minute config lockout when a **new platform**
    (e.g. Windows while an iPhone slot is already active) would exceed
    ``device_limit``. Same phone with a new public IP — carrier change or a
    sub refresh that egresses through the VPN — does **not** count as another
    device.
    """
    hw = (hwid or "").strip()
    ua = (user_agent or "").strip()
    # Opening the subscribe web UI (PC or phone browser) must not create a
    # platform slot — that was locking brand-new accounts on first app import.
    if _is_browser_ua(ua):
        return
    if _is_infrastructure_ip(client_ip) and not hw and not ua:
        return

    now = datetime.utcnow()
    platform = classify_client_platform(user_agent)
    key = device_fingerprint(client_ip, user_agent=user_agent, hwid=hwid)
    ips = _client_device_entries(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))
    ips = _collapse_same_platform(ips, platform, keep_key=key)

    prev = ips.get(key) if isinstance(ips.get(key), dict) else {}
    apps = []
    prev_apps = prev.get("apps") if isinstance(prev, dict) else None
    if isinstance(prev_apps, list):
        apps = [str(a) for a in prev_apps][:8]
    if ua and ua not in apps:
        apps.append(ua[:80])
        apps = apps[-8:]

    usable_ip = bool(client_ip) and not _is_infrastructure_ip(client_ip)
    active_slots = _active_platform_slots(ips, now)
    platform_known = platform in active_slots

    limit = getattr(dbuser, "device_limit", None)
    try:
        cap = int(limit) if limit is not None else 0
    except (TypeError, ValueError):
        cap = 0
    if enforce and cap > 0 and not platform_known and len(active_slots) >= cap:
        start_device_lockout(
            db,
            dbuser,
            minutes=DEVICE_LOCKOUT_MINUTES,
            extra_ip=client_ip if usable_ip else "",
            extra_ua=ua,
            extra_platform=platform,
        )
        return

    # Keep only the latest IP for this platform (evidence); do not accumulate
    # churned addresses that previously looked like "extra devices".
    recent_ips: dict[str, str] = {}
    if usable_ip:
        recent_ips[client_ip] = now.isoformat()

    entry = {
        "seen": now.isoformat(),
        "ip": client_ip if usable_ip else (prev.get("ip") if isinstance(prev, dict) else client_ip),
        "ua": (user_agent or "")[:180],
        "platform": platform,
        "hwid_hint": (hw[:32] if hw else ""),
        "apps": apps,
        "recent_ips": recent_ips,
    }
    ips[key] = entry
    dbuser.device_ips = json.dumps(ips)
    if db is not None:
        db.commit()


def apply_subscription_device_policy(
    db: Session,
    dbuser: User,
    client_ip: str,
    user_agent: str = "",
    hwid: str = "",
) -> Optional[dict[str, Any]]:
    """Subscription-time device gate.

    Returns ``None`` when configs may be exported. Otherwise returns
    ``{"block_reason": "device_limit", "minutes_left": N, "message": "...",
       "blocked_devices": [...]}``.
    """
    remaining = get_device_lockout_remaining(dbuser)
    if remaining is not None:
        minutes_left = max(1, (remaining + 59) // 60)
        evidence = get_device_lockout_evidence(dbuser)
        return {
            "block_reason": "device_limit",
            "minutes_left": minutes_left,
            "lockout_seconds_left": int(remaining),
            "message": format_device_lockout_report(
                dbuser, minutes_left=minutes_left, evidence=evidence
            ),
            "blocked_devices": evidence,
        }

    limit = getattr(dbuser, "device_limit", None)
    if not limit or int(limit) <= 0:
        record_and_check_device_limit(
            db, dbuser, client_ip, user_agent=user_agent, hwid=hwid, enforce=False
        )
        return None

    record_and_check_device_limit(
        db, dbuser, client_ip, user_agent=user_agent, hwid=hwid, enforce=True
    )
    remaining = get_device_lockout_remaining(dbuser)
    if remaining is not None:
        minutes_left = max(1, (remaining + 59) // 60)
        evidence = get_device_lockout_evidence(dbuser)
        return {
            "block_reason": "device_limit",
            "minutes_left": minutes_left,
            "lockout_seconds_left": int(remaining),
            "message": format_device_lockout_report(
                dbuser, minutes_left=minutes_left, evidence=evidence
            ),
            "blocked_devices": evidence,
        }
    return None


def device_lockout_message(minutes_left: int, dbuser: Optional[User] = None) -> str:
    """Short one-line fallback; prefer ``format_device_lockout_report`` when user known."""
    if dbuser is not None:
        return format_device_lockout_report(dbuser, minutes_left=int(minutes_left))
    from config import SUB_BLOCKED_DEVICE_LIMIT_MESSAGE

    base = SUB_BLOCKED_DEVICE_LIMIT_MESSAGE
    try:
        return base.format(minutes=int(minutes_left))
    except Exception:
        return f"{base} ({int(minutes_left)} دقیقه)"


# Consecutive over-limit usage ticks before live lockout (see enforce_live_device_limits).
# Higher than 1 so a brief reconnect / dual-inbound blip does not hide configs.
_LIVE_OVER_STREAK: dict[int, int] = {}
_LIVE_OVER_STREAK_NEED = 3


def enforce_live_device_limits(candidate_uids: Optional[Iterable] = None) -> int:
    """Kick + lockout when live Xray online IPs stay over ``device_limit``.

    Requires two consecutive over-limit observations before locking so a brief
    NAT/reconnect spike does not hide configs for 30 minutes. Once locked,
    subscription exports stay blocked until the timer expires.
    """
    from app.db import GetDB
    from app.models.user import UserStatus

    kicked = 0

    with GetDB() as db:
        q = db.query(User).filter(
            User.device_limit.isnot(None),
            User.device_limit > 0,
            User.status.in_([UserStatus.active, UserStatus.on_hold]),
        )
        if candidate_uids is not None:
            ids = [int(u) for u in candidate_uids]
            if not ids:
                return 0
            q = q.filter(User.id.in_(ids))
        users = q.all()
        targets = [(int(u.id), int(u.device_limit), u) for u in users]

    still_hot: set[int] = set()
    for uid, limit, dbuser in targets:
        try:
            n = _xray_online_device_count(dbuser)
        except Exception:
            continue
        if n is None or n <= limit:
            _LIVE_OVER_STREAK.pop(uid, None)
            continue
        streak = int(_LIVE_OVER_STREAK.get(uid, 0)) + 1
        _LIVE_OVER_STREAK[uid] = streak
        still_hot.add(uid)
        if streak < _LIVE_OVER_STREAK_NEED:
            logger.info(
                "device limit over live user_id=%s online=%s limit=%s streak=%s/%s",
                uid,
                n,
                limit,
                streak,
                _LIVE_OVER_STREAK_NEED,
            )
            continue
        try:
            from app.xray.operations import update_user
            from app.xray.serving import hot_disconnect_users

            with GetDB() as db:
                row = db.query(User).filter(User.id == uid).first()
                if row is None:
                    continue
                if get_device_lockout_remaining(row) is None:
                    start_device_lockout(
                        db,
                        row,
                        minutes=DEVICE_LOCKOUT_MINUTES,
                        reason="device_limit_live",
                    )
                hot_disconnect_users([row])
                update_user(row)
            kicked += 1
            logger.info(
                "device limit live-kick+lockout user_id=%s online=%s limit=%s",
                uid,
                n,
                limit,
            )
        except Exception:
            logger.debug("device limit kick failed for %s", uid, exc_info=True)

    if candidate_uids is None:
        for stale in list(_LIVE_OVER_STREAK.keys()):
            if stale not in still_hot:
                _LIVE_OVER_STREAK.pop(stale, None)
    return kicked
