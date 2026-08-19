import ipaddress
import math
import secrets
import socket
import threading
import time
from dataclasses import dataclass

import psutil
import requests

from app import scheduler

# Public IP probes hit external HTTP APIs; cache so hot paths (subscription
# device-limit) never stall clients for multiple probe timeouts.
_PUBLIC_IP_CACHE_TTL = 3600.0


@dataclass
class MemoryStat():
    total: int
    used: int
    free: int


@dataclass
class CPUStat():
    cores: int
    percent: float


@dataclass
class DiskStat():
    total: int
    used: int
    free: int


# Cached CPU sample from ``/proc/stat`` over a ~1s sliding window (same as
# top/htop). Ticks still run every 250ms; a 250ms-only window is too noisy.
# Never use ``cpu_percent(interval=N)`` here — that blocks the WebSocket loop.
_cpu_cached_percent: float = 0.0
_cpu_cached_cores: int = 0
_cpu_sampler_primed: bool = False
_cpu_hist: list[tuple[float, int, int]] = []
_CPU_WINDOW_SEC = 1.0


def _read_cpu_times() -> tuple[int, int] | None:
    """Return (busy, total) jiffies from ``/proc/stat`` (host, like top)."""
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            parts = fh.readline().split()
        nums = [int(x) for x in parts[1:8]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        return total - idle, total
    except (OSError, ValueError, IndexError):
        return None


def _sample_cpu_percent() -> float:
    """System-wide CPU % over the last ~1s (one decimal, htop-style)."""
    global _cpu_cached_percent, _cpu_cached_cores, _cpu_sampler_primed, _cpu_hist
    cores = psutil.cpu_count(logical=True) or 1
    _cpu_cached_cores = int(cores)
    times = _read_cpu_times()
    if times is None:
        _cpu_cached_percent = round(float(psutil.cpu_percent(interval=None) or 0.0), 1)
        _cpu_sampler_primed = True
        return _cpu_cached_percent
    busy, total = times
    now = time.monotonic()
    _cpu_hist.append((now, busy, total))
    cutoff = now - _CPU_WINDOW_SEC
    drop_to = 0
    for i, (ts, _b, _t) in enumerate(_cpu_hist):
        if ts >= cutoff:
            drop_to = max(0, i - 1)
            break
    if drop_to:
        del _cpu_hist[:drop_to]
    if len(_cpu_hist) > 16:
        del _cpu_hist[:-16]
    prev = _cpu_hist[0]
    if len(_cpu_hist) >= 2 and total > prev[2]:
        d_total = total - prev[2]
        d_busy = busy - prev[1]
        _cpu_cached_percent = round(max(0.0, min(100.0, 100.0 * d_busy / d_total)), 1)
    _cpu_sampler_primed = True
    return _cpu_cached_percent


def cpu_usage() -> CPUStat:
    """Return last sampled CPU % (panel host). Prefer cache; sample once if cold."""
    if not _cpu_sampler_primed:
        _sample_cpu_percent()
    return CPUStat(
        cores=_cpu_cached_cores or (psutil.cpu_count(logical=True) or 1),
        percent=float(_cpu_cached_percent),
    )


def _read_host_meminfo() -> tuple[int, int] | None:
    """MemTotal / MemAvailable from the kernel (bytes). Matches ``free`` / htop."""
    total = avail = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                if total is not None and avail is not None:
                    return total, avail
    except (OSError, ValueError, IndexError):
        return None
    return None


def memory_usage() -> MemoryStat:
    """Used = Total − Available (same as htop, not cache-inflated ``MemUsed``)."""
    parsed = _read_host_meminfo()
    if parsed is not None:
        total, avail = parsed
        used = max(0, int(total) - int(avail))
        return MemoryStat(total=int(total), used=used, free=int(avail))
    mem = psutil.virtual_memory()
    avail = int(mem.available)
    total = int(mem.total)
    return MemoryStat(total=total, used=max(0, total - avail), free=avail)


_disk_cached: DiskStat | None = None
_disk_cached_at: float = 0.0


def disk_usage(path: str = "/") -> DiskStat:
    global _disk_cached, _disk_cached_at
    now = time.monotonic()
    if _disk_cached is not None and (now - _disk_cached_at) < 5.0:
        return _disk_cached
    disk = psutil.disk_usage(path)
    _disk_cached = DiskStat(total=disk.total, used=disk.used, free=disk.free)
    _disk_cached_at = now
    return _disk_cached


def os_uptime() -> int:
    """Seconds since the host booted."""
    return max(0, int(time.time() - psutil.boot_time()))


@dataclass
class RealtimeBandwidth:
    def __post_init__(self):
        io = psutil.net_io_counters()
        self.bytes_recv = io.bytes_recv
        self.bytes_sent = io.bytes_sent
        self.packets_recv = io.packets_recv
        self.packets_sent = io.packets_sent
        self.last_perf_counter = time.perf_counter()

    # data in the form of value per seconds
    incoming_bytes: int
    outgoing_bytes: int
    incoming_packets: int
    outgoing_packets: int

    bytes_recv: int = None
    bytes_sent: int = None
    packets_recv: int = None
    packets_sent: int = None
    last_perf_counter: float = None


@dataclass
class RealtimeBandwidthStat:
    """Real-Time bandwith in value/s unit"""

    incoming_bytes: int
    outgoing_bytes: int
    incoming_packets: int
    outgoing_packets: int


rt_bw = RealtimeBandwidth(
    incoming_bytes=0, outgoing_bytes=0, incoming_packets=0, outgoing_packets=0)

# Xray inbound throughput (proxy only — not whole-NIC psutil noise).
# Do NOT seed from NIC counters: mixing NIC baselines with Xray totals makes the
# first delta nonsense and can pin rates at 0 after xr_bw_ready flips True.
xr_bw = RealtimeBandwidth(
    incoming_bytes=0, outgoing_bytes=0, incoming_packets=0, outgoing_packets=0)
xr_bw.bytes_recv = None
xr_bw.bytes_sent = None
xr_bw.packets_recv = None
xr_bw.packets_sent = None
xr_bw.last_perf_counter = None
xr_bw_ready = False
# How many Xray APIs contributed to the last successful fleet sample (panel=1).
xr_bw_sources = 0
# Per-source cumulative (up, down) from the previous tick. Fleet rate is the
# sum of per-source deltas so a node dropping out of the sample cannot make
# the total go backwards and pin Overview at 0 B/s.
_xr_prev: dict = {}
# Skip nodes that recently Deadline-Exceeded so the 2–5s bandwidth tick does
# not keep hammering slow Iran control-tunnel paths.
_xr_bw_fail_until: dict = {}
_XR_BW_FAIL_COOLDOWN = 45.0
_XR_BW_RPC_TIMEOUT = 1.5
_XR_BW_FUTURE_TIMEOUT = 2.0


def _live_xray_apis() -> dict:
    """Panel Xray API plus every connected node that has a live Stats API."""
    from app import xray

    now = time.monotonic()
    apis = {None: xray.api}
    for node_id, node in list(getattr(xray, "nodes", {}).items()):
        if now < float(_xr_bw_fail_until.get(node_id, 0.0) or 0.0):
            continue
        try:
            if getattr(node, "has_live_api", None) and node.has_live_api():
                apis[node_id] = node.api
            elif getattr(node, "started", False) and getattr(node, "_api", None) is not None:
                apis[node_id] = node.api
        except Exception:
            continue
    return {nid: api for nid, api in apis.items() if api is not None}


def _sum_link_counters(api, *, prefer_inbound: bool = True, node_id=None) -> tuple[int, int]:
    """Return (uplink, downlink) cumulative bytes on one core.

    Prefer inbound counters (stable; not reset by usage jobs). Fall back to
    outbound when inbound stats are still disabled on an older core config.
    """
    def _sum(stats) -> tuple[int, int]:
        up = down = 0
        for stat in stats:
            if not getattr(stat, "value", 0):
                continue
            if stat.link == "uplink":
                up += int(stat.value)
            else:
                down += int(stat.value)
        return up, down

    try:
        if prefer_inbound:
            try:
                up, down = _sum(api.get_inbounds_stats(reset=False, timeout=_XR_BW_RPC_TIMEOUT))
                if up or down:
                    return up, down
            except Exception:
                pass
        up, down = _sum(api.get_outbounds_stats(reset=False, timeout=_XR_BW_RPC_TIMEOUT))
        return up, down
    except Exception:
        if node_id is not None:
            _xr_bw_fail_until[node_id] = time.monotonic() + _XR_BW_FAIL_COOLDOWN
        raise


def _per_source_link_rates(prev: dict, current: dict, dt: float):
    """Rate from sources present in *both* samples.

    Returns ``(in_bps, out_bps)`` or ``(None, None)`` when nothing is
    comparable (first sample, every source reset, or empty). Callers must
    keep the last displayed rate in the None case — writing 0 is what made
    Overview flatline whenever a node timed out or usage reset counters.
    """
    if dt <= 0 or not current:
        return None, None
    d_up = d_down = 0
    comparable = 0
    for nid, pair in current.items():
        old = prev.get(nid)
        if old is None:
            continue
        try:
            up, down = pair
            pu, pd = old
            du = int(up) - int(pu)
            dd = int(down) - int(pd)
        except (TypeError, ValueError):
            continue
        if du < 0 or dd < 0:
            continue
        d_up += du
        d_down += dd
        comparable += 1
    if comparable == 0:
        return None, None
    return max(0, round(d_up / dt)), max(0, round(d_down / dt))


def _sample_xray_inbound_rates() -> None:
    """Fleet Overall Speed from panel + every connected node (3x-ui style).

    Polarity matches 3x-ui Overall Speed / NetIO (server view):
      Upload   = bytes the server sends   ≈ downlink (to clients / from net)
      Download = bytes the server receives ≈ uplink (from clients / to net)

    Same delta/dt approach as 3x-ui ``Status.NetIO``, but summed across the
    whole fleet's Xray cores instead of only the panel host NIC.
    """
    global xr_bw, xr_bw_ready, xr_bw_sources, _xr_prev
    try:
        apis = _live_xray_apis()
        if not apis:
            xr_bw_ready = False
            xr_bw_sources = 0
            return

        total_up = total_down = 0
        current: dict = {}
        from app.utils.concurrency import map_rpc

        def _one(nid, api):
            return _sum_link_counters(api, node_id=nid)

        results = map_rpc(_one, apis, timeout=_XR_BW_FUTURE_TIMEOUT, default=None)
        for nid, pair in results.items():
            if not pair:
                if nid is not None:
                    _xr_bw_fail_until[nid] = time.monotonic() + _XR_BW_FAIL_COOLDOWN
                continue
            try:
                up, down = pair
                total_up += up
                total_down += down
                current[nid] = (int(up), int(down))
                _xr_bw_fail_until.pop(nid, None)
            except Exception:
                if nid is not None:
                    _xr_bw_fail_until[nid] = time.monotonic() + _XR_BW_FAIL_COOLDOWN
                continue

        ok = len(current)
        if ok == 0:
            xr_bw_ready = False
            xr_bw_sources = 0
            return

        last_t = xr_bw.last_perf_counter
        now = time.perf_counter()
        dt = (now - last_t) if last_t is not None else 0.0
        in_bps, out_bps = _per_source_link_rates(_xr_prev, current, dt)
        if in_bps is not None:
            # Download card ← server RX ← uplink
            xr_bw.incoming_bytes = in_bps
            # Upload card ← server TX ← downlink
            xr_bw.outgoing_bytes = out_bps
        _xr_prev = current
        xr_bw.bytes_sent = total_up
        xr_bw.bytes_recv = total_down
        xr_bw.last_perf_counter = now
        xr_bw_ready = True
        xr_bw_sources = ok
    except Exception:
        xr_bw_ready = False
        xr_bw_sources = 0


# Same family of exclusions as 3x-ui ``isVirtualInterface``.
_VIRTUAL_NIC_PREFIXES = (
    "lo", "loopback", "docker", "br-", "veth", "virbr",
    "tun", "tap", "wg", "tailscale", "zt",
)


def _nic_io_totals() -> tuple[int, int, int, int]:
    """Sum host NIC counters, skipping virtual interfaces (3x-ui NetIO style)."""
    try:
        per_nic = psutil.net_io_counters(pernic=True) or {}
    except Exception:
        per_nic = {}
    if not per_nic:
        io = psutil.net_io_counters()
        return io.bytes_sent, io.bytes_recv, io.packets_sent, io.packets_recv

    sent = recv = pkts_sent = pkts_recv = 0
    for name, io in per_nic.items():
        low = (name or "").lower()
        if any(low == p or low.startswith(p) for p in _VIRTUAL_NIC_PREFIXES):
            continue
        sent += int(io.bytes_sent)
        recv += int(io.bytes_recv)
        pkts_sent += int(io.packets_sent)
        pkts_recv += int(io.packets_recv)
    if sent or recv:
        return sent, recv, pkts_sent, pkts_recv
    io = psutil.net_io_counters()
    return io.bytes_sent, io.bytes_recv, io.packets_sent, io.packets_recv


# Host gauges + WebSocket tick every second on a dedicated thread so a
# saturated APScheduler pool cannot stall Overview.
def record_realtime_bandwidth() -> None:
    global rt_bw
    # Keep CPU gauge fresh on the same tick so Overview matches host top/htop.
    try:
        _sample_cpu_percent()
    except Exception:
        pass
    last_perf_counter = rt_bw.last_perf_counter
    sent, recv, pkts_sent, pkts_recv = _nic_io_totals()
    now = time.perf_counter()
    rt_bw.last_perf_counter = now
    if last_perf_counter is None:
        sample_time = 0.0
    else:
        sample_time = now - last_perf_counter
    if sample_time > 0:
        rt_bw.incoming_bytes = max(0, round((recv - (rt_bw.bytes_recv or 0)) / sample_time))
        rt_bw.outgoing_bytes = max(0, round((sent - (rt_bw.bytes_sent or 0)) / sample_time))
        rt_bw.incoming_packets = max(0, round((pkts_recv - (rt_bw.packets_recv or 0)) / sample_time))
        rt_bw.outgoing_packets = max(0, round((pkts_sent - (rt_bw.packets_sent or 0)) / sample_time))
    rt_bw.bytes_recv = recv
    rt_bw.bytes_sent = sent
    rt_bw.packets_recv = pkts_recv
    rt_bw.packets_sent = pkts_sent
    try:
        from app.runtime_role import owns_control_plane
        from app.sync.wake import publish_bandwidth

        if owns_control_plane():
            publish_bandwidth(
                {
                    "xr_ready": bool(xr_bw_ready),
                    "xr_sources": int(xr_bw_sources),
                    "xr_in": int(xr_bw.incoming_bytes),
                    "xr_out": int(xr_bw.outgoing_bytes),
                    "rt_in": int(rt_bw.incoming_bytes),
                    "rt_out": int(rt_bw.outgoing_bytes),
                    "rt_in_pkts": int(rt_bw.incoming_packets),
                    "rt_out_pkts": int(rt_bw.outgoing_packets),
                }
            )
            try:
                from app.sync.live import publish_tick

                publish_tick()
            except Exception:
                pass
    except Exception:
        pass


_overview_tick_thread: threading.Thread | None = None
_overview_tick_stop = threading.Event()


def start_overview_live_ticks() -> None:
    """Push Overview KPIs over Redis pub/sub.

    CPU/RAM run in a child process (own GIL) so fleet QueryStats cannot freeze
    the gauges. Bandwidth stays on this thread.
    """
    global _overview_tick_thread
    try:
        from app.sync.host_tick import start_host_tick_process

        start_host_tick_process()
    except Exception:
        pass
    if _overview_tick_thread is not None and _overview_tick_thread.is_alive():
        return

    def _loop() -> None:
        while not _overview_tick_stop.wait(0):
            t0 = time.monotonic()
            try:
                record_realtime_bandwidth()
            except Exception:
                pass
            leftover = 0.25 - (time.monotonic() - t0)
            if leftover < 0.02:
                leftover = 0.02
            if _overview_tick_stop.wait(leftover):
                break

    _overview_tick_thread = threading.Thread(
        target=_loop, name="overview-ws-tick", daemon=True
    )
    _overview_tick_thread.start()
    try:
        from app import logger as _log

        _log.info("overview WebSocket ticks started (250ms host CPU/RAM process)")
    except Exception:
        pass


@scheduler.scheduled_job("interval", seconds=2, coalesce=True, max_instances=1)
def refresh_live_census() -> None:
    """Refresh Overview user/node counts off the 1s WebSocket tick path."""
    try:
        from app.runtime_role import owns_control_plane

        if not owns_control_plane():
            return
        from app.sync.live import load_census, publish_tick

        load_census(force=True)
        publish_tick()
    except Exception:
        pass


@scheduler.scheduled_job("interval", seconds=2, coalesce=True, max_instances=1)
def sample_fleet_xray_bandwidth() -> None:
    """Fleet inbound counters for Overview speed. Never runs inside the HTTP process."""
    try:
        from app.runtime_role import owns_control_plane

        if not owns_control_plane():
            return
    except Exception:
        return
    _sample_xray_inbound_rates()


# Ignore tiny Xray counter noise; below this, prefer host NIC like 3x-ui.
_FLEET_RATE_FLOOR = 8_192  # 8 KiB/s


def _use_fleet_bandwidth() -> bool:
    if not xr_bw_ready:
        return False
    fleet_idle = (
        xr_bw.incoming_bytes < _FLEET_RATE_FLOOR
        and xr_bw.outgoing_bytes < _FLEET_RATE_FLOOR
    )
    nic_busy = (
        rt_bw.incoming_bytes >= _FLEET_RATE_FLOOR
        or rt_bw.outgoing_bytes >= _FLEET_RATE_FLOOR
    )
    # A partial fleet sample (node timeout / counter reset) used to publish
    # 0 B/s while the host NIC still saw traffic. Prefer NIC in that gap.
    if fleet_idle and nic_busy:
        return False
    # Multi-node sample: trust the fleet aggregate (including genuine idle).
    if xr_bw_sources > 1:
        return True
    return (
        xr_bw.incoming_bytes >= _FLEET_RATE_FLOOR
        or xr_bw.outgoing_bytes >= _FLEET_RATE_FLOOR
    )


def realtime_bandwidth() -> RealtimeBandwidthStat:
    """Fleet Xray (panel + nodes) when it carries real traffic; else host NIC.

    3x-ui Overall Speed is host NetIO. We extend that for Shahkar by summing
    Xray counters across every connected node so Home shows whole-fleet proxy
    throughput instead of only the panel box.
    """
    try:
        from app.runtime_role import owns_control_plane
        from app.sync.wake import load_bandwidth

        if not owns_control_plane():
            remote = load_bandwidth()
            if remote:
                xr_in = int(remote.get("xr_in") or 0)
                xr_out = int(remote.get("xr_out") or 0)
                rt_in = int(remote.get("rt_in") or 0)
                rt_out = int(remote.get("rt_out") or 0)
                fleet_idle = xr_in < _FLEET_RATE_FLOOR and xr_out < _FLEET_RATE_FLOOR
                nic_busy = rt_in >= _FLEET_RATE_FLOOR or rt_out >= _FLEET_RATE_FLOOR
                if (
                    remote.get("xr_ready")
                    and not (fleet_idle and nic_busy)
                    and (
                        int(remote.get("xr_sources") or 0) > 1
                        or xr_in >= _FLEET_RATE_FLOOR
                        or xr_out >= _FLEET_RATE_FLOOR
                    )
                ):
                    return RealtimeBandwidthStat(
                        incoming_bytes=xr_in,
                        outgoing_bytes=xr_out,
                        incoming_packets=0,
                        outgoing_packets=0,
                    )
                return RealtimeBandwidthStat(
                    incoming_bytes=rt_in,
                    outgoing_bytes=rt_out,
                    incoming_packets=int(remote.get("rt_in_pkts") or 0),
                    outgoing_packets=int(remote.get("rt_out_pkts") or 0),
                )
    except Exception:
        pass
    if _use_fleet_bandwidth():
        return RealtimeBandwidthStat(
            incoming_bytes=xr_bw.incoming_bytes,
            outgoing_bytes=xr_bw.outgoing_bytes,
            incoming_packets=xr_bw.incoming_packets,
            outgoing_packets=xr_bw.outgoing_packets,
        )
    return RealtimeBandwidthStat(
        incoming_bytes=rt_bw.incoming_bytes,
        outgoing_bytes=rt_bw.outgoing_bytes,
        incoming_packets=rt_bw.incoming_packets,
        outgoing_packets=rt_bw.outgoing_packets,
    )


def realtime_bandwidth_source() -> str:
    try:
        from app.runtime_role import owns_control_plane
        from app.sync.wake import load_bandwidth

        if not owns_control_plane():
            remote = load_bandwidth()
            if remote and remote.get("xr_ready"):
                xr_in = int(remote.get("xr_in") or 0)
                xr_out = int(remote.get("xr_out") or 0)
                rt_in = int(remote.get("rt_in") or 0)
                rt_out = int(remote.get("rt_out") or 0)
                fleet_idle = xr_in < _FLEET_RATE_FLOOR and xr_out < _FLEET_RATE_FLOOR
                nic_busy = rt_in >= _FLEET_RATE_FLOOR or rt_out >= _FLEET_RATE_FLOOR
                if not (fleet_idle and nic_busy):
                    return "fleet" if int(remote.get("xr_sources") or 0) > 1 else "xray"
            if remote:
                return "nic"
    except Exception:
        pass
    if _use_fleet_bandwidth():
        return "fleet" if xr_bw_sources > 1 else "xray"
    return "nic"


def random_password() -> str:
    return secrets.token_urlsafe(16)


def check_port(port: int) -> bool:
    s = socket.socket()
    try:
        s.connect(('127.0.0.1', port))
        return True
    except socket.error:
        return False
    finally:
        s.close()


def get_public_ip():
    """Return the panel's public IPv4.

    Cached: subscription device-limit checks call this on every app import.
    Uncached HTTP probes (ipify ×3, 5s each) made Clash/v2rayN imports hang
    ~15s and fail on clients with short timeouts.
    """
    now = time.monotonic()
    cached = getattr(get_public_ip, "_cache", None)
    if cached and (now - cached[0]) < _PUBLIC_IP_CACHE_TTL:
        return cached[1]

    ip = _detect_public_ipv4()
    get_public_ip._cache = (now, ip)
    return ip


def _detect_public_ipv4() -> str:
    try:
        resp = requests.get('http://api4.ipify.org/', timeout=1.5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except Exception:
        pass

    try:
        resp = requests.get('http://ipv4.icanhazip.com/', timeout=1.5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except Exception:
        pass

    try:
        requests.packages.urllib3.util.connection.HAS_IPV6 = False
        resp = requests.get('https://ifconfig.io/ip', timeout=1.5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except requests.exceptions.RequestException:
        pass
    finally:
        requests.packages.urllib3.util.connection.HAS_IPV6 = True

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.connect(('8.8.8.8', 80))
        resp = sock.getsockname()[0]
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except (socket.error, IndexError, OSError):
        pass
    finally:
        if sock is not None:
            sock.close()

    return '127.0.0.1'


def get_public_ipv6():
    now = time.monotonic()
    cached = getattr(get_public_ipv6, "_cache", None)
    if cached and (now - cached[0]) < _PUBLIC_IP_CACHE_TTL:
        return cached[1]

    ip = _detect_public_ipv6()
    get_public_ipv6._cache = (now, ip)
    return ip


def _detect_public_ipv6() -> str:
    try:
        resp = requests.get('http://api6.ipify.org/', timeout=1.5).text.strip()
        if ipaddress.IPv6Address(resp).is_global:
            return '[%s]' % resp
    except Exception:
        pass

    try:
        resp = requests.get('http://ipv6.icanhazip.com/', timeout=1.5).text.strip()
        if ipaddress.IPv6Address(resp).is_global:
            return '[%s]' % resp
    except Exception:
        pass

    return '[::1]'


def readable_size(size_bytes):
    if size_bytes <= 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f'{s} {size_name[i]}'
