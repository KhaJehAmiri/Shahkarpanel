import ipaddress
import math
import secrets
import socket
import time
from concurrent.futures import ThreadPoolExecutor
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


def cpu_usage() -> CPUStat:
    return CPUStat(cores=psutil.cpu_count(), percent=psutil.cpu_percent())


def memory_usage() -> MemoryStat:
    mem = psutil.virtual_memory()
    return MemoryStat(total=mem.total, used=mem.used, free=mem.available)


def disk_usage(path: str = "/") -> DiskStat:
    disk = psutil.disk_usage(path)
    return DiskStat(total=disk.total, used=disk.used, free=disk.free)


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


def _sample_xray_inbound_rates() -> None:
    """Fleet Overall Speed from panel + every connected node (3x-ui style).

    Polarity matches 3x-ui Overall Speed / NetIO (server view):
      Upload   = bytes the server sends   ≈ downlink (to clients / from net)
      Download = bytes the server receives ≈ uplink (from clients / to net)

    Same delta/dt approach as 3x-ui ``Status.NetIO``, but summed across the
    whole fleet's Xray cores instead of only the panel host NIC.
    """
    global xr_bw, xr_bw_ready, xr_bw_sources
    try:
        apis = _live_xray_apis()
        if not apis:
            xr_bw_ready = False
            xr_bw_sources = 0
            return

        total_up = total_down = 0
        ok = 0
        workers = min(8, max(1, len(apis)))
        # Do NOT use ``with ThreadPoolExecutor``: after ``future.result(timeout=…)``
        # the context manager still ``shutdown(wait=True)``, so one hung node RPC
        # blocks the bandwidth job forever (max_instances=1 → Overview freeze).
        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                nid: executor.submit(_sum_link_counters, api, node_id=nid)
                for nid, api in apis.items()
            }
            for nid, fut in futures.items():
                try:
                    up, down = fut.result(timeout=_XR_BW_FUTURE_TIMEOUT)
                    total_up += up
                    total_down += down
                    ok += 1
                    _xr_bw_fail_until.pop(nid, None)
                except Exception:
                    if nid is not None:
                        _xr_bw_fail_until[nid] = time.monotonic() + _XR_BW_FAIL_COOLDOWN
                    continue
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if ok == 0:
            xr_bw_ready = False
            xr_bw_sources = 0
            return

        last_t = xr_bw.last_perf_counter
        prev_up = xr_bw.bytes_sent
        prev_down = xr_bw.bytes_recv
        now = time.perf_counter()
        if last_t is not None and prev_up is not None and prev_down is not None:
            dt = now - last_t
            if dt > 0:
                d_up = total_up - prev_up
                d_down = total_down - prev_down
                if d_up < 0 or d_down < 0:
                    # Outbound counters are periodically reset by usage jobs.
                    xr_bw.incoming_bytes = 0
                    xr_bw.outgoing_bytes = 0
                else:
                    # Download card ← server RX ← uplink
                    xr_bw.incoming_bytes = max(0, round(d_up / dt))
                    # Upload card ← server TX ← downlink
                    xr_bw.outgoing_bytes = max(0, round(d_down / dt))
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


# sample time is 5 seconds (was 2): digicdn's 14 tunneled nodes cannot answer
# Stats RPC that often without starving the API worker.
@scheduler.scheduled_job("interval", seconds=5, coalesce=True, max_instances=1)
def record_realtime_bandwidth() -> None:
    global rt_bw
    last_perf_counter = rt_bw.last_perf_counter
    sent, recv, pkts_sent, pkts_recv = _nic_io_totals()
    now = time.perf_counter()
    rt_bw.last_perf_counter = now
    if last_perf_counter is None:
        sample_time = 0.0
    else:
        sample_time = now - last_perf_counter
    if sample_time > 0:
        rt_bw.incoming_bytes = round((recv - (rt_bw.bytes_recv or 0)) / sample_time)
        rt_bw.outgoing_bytes = round((sent - (rt_bw.bytes_sent or 0)) / sample_time)
        rt_bw.incoming_packets = round((pkts_recv - (rt_bw.packets_recv or 0)) / sample_time)
        rt_bw.outgoing_packets = round((pkts_sent - (rt_bw.packets_sent or 0)) / sample_time)
    rt_bw.bytes_recv = recv
    rt_bw.bytes_sent = sent
    rt_bw.packets_recv = pkts_recv
    rt_bw.packets_sent = pkts_sent
    _sample_xray_inbound_rates()


# Ignore tiny Xray counter noise; below this, prefer host NIC like 3x-ui.
_FLEET_RATE_FLOOR = 8_192  # 8 KiB/s


def _use_fleet_bandwidth() -> bool:
    if not xr_bw_ready:
        return False
    # Multi-node sample: always trust the fleet aggregate (even when idle).
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
