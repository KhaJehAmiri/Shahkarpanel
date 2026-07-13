import ipaddress
import math
import secrets
import socket
import time
from dataclasses import dataclass

import psutil
import requests

from app import scheduler


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


def _sample_xray_inbound_rates() -> None:
    """Sum all inbound uplink/downlink counters and derive bytes/s."""
    global xr_bw, xr_bw_ready
    try:
        from app import xray

        up = down = 0
        for stat in xray.api.get_inbounds_stats(reset=False, timeout=5):
            if stat.link == "uplink":
                up += stat.value
            else:
                down += stat.value

        last_t = xr_bw.last_perf_counter
        prev_recv = xr_bw.bytes_recv
        prev_sent = xr_bw.bytes_sent
        now = time.perf_counter()
        if last_t is not None and prev_recv is not None and prev_sent is not None:
            dt = now - last_t
            if dt > 0:
                # downlink = traffic to clients (دانلود کاربر), uplink = آپلود کاربر
                xr_bw.incoming_bytes = max(0, round((down - prev_recv) / dt))
                xr_bw.outgoing_bytes = max(0, round((up - prev_sent) / dt))
        xr_bw.bytes_recv = down
        xr_bw.bytes_sent = up
        xr_bw.last_perf_counter = now
        xr_bw_ready = True
    except Exception:
        xr_bw_ready = False


# sample time is 2 seconds, values lower than this may not produce good results
@scheduler.scheduled_job("interval", seconds=2, coalesce=True, max_instances=1)
def record_realtime_bandwidth() -> None:
    global rt_bw
    last_perf_counter = rt_bw.last_perf_counter
    io = psutil.net_io_counters()
    now = time.perf_counter()
    rt_bw.last_perf_counter = now
    if last_perf_counter is None:
        sample_time = 0.0
    else:
        sample_time = now - last_perf_counter
    if sample_time > 0:
        rt_bw.incoming_bytes = round((io.bytes_recv - (rt_bw.bytes_recv or 0)) / sample_time)
        rt_bw.outgoing_bytes = round((io.bytes_sent - (rt_bw.bytes_sent or 0)) / sample_time)
        rt_bw.incoming_packets = round((io.packets_recv - (rt_bw.packets_recv or 0)) / sample_time)
        rt_bw.outgoing_packets = round((io.packets_sent - (rt_bw.packets_sent or 0)) / sample_time)
    rt_bw.bytes_recv = io.bytes_recv
    rt_bw.bytes_sent = io.bytes_sent
    rt_bw.packets_recv = io.packets_recv
    rt_bw.packets_sent = io.packets_sent
    _sample_xray_inbound_rates()


def realtime_bandwidth() -> RealtimeBandwidthStat:
    """Prefer Xray inbound rates (proxy). Fall back to whole-server NIC via psutil.

    When Xray stats are reachable but idle (common while traffic flows through
    nodes rather than panel inbounds), fall back to NIC so Home stays live.
    """
    if xr_bw_ready and (xr_bw.incoming_bytes > 0 or xr_bw.outgoing_bytes > 0):
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
    if xr_bw_ready and (xr_bw.incoming_bytes > 0 or xr_bw.outgoing_bytes > 0):
        return "xray"
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
    try:
        resp = requests.get('http://api4.ipify.org/', timeout=5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except Exception:
        pass

    try:
        resp = requests.get('http://ipv4.icanhazip.com/', timeout=5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except Exception:
        pass

    try:
        requests.packages.urllib3.util.connection.HAS_IPV6 = False
        resp = requests.get('https://ifconfig.io/ip', timeout=5).text.strip()
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except requests.exceptions.RequestException:
        pass
    finally:
        requests.packages.urllib3.util.connection.HAS_IPV6 = True

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        resp = sock.getsockname()[0]
        if ipaddress.IPv4Address(resp).is_global:
            return resp
    except (socket.error, IndexError):
        pass
    finally:
        sock.close()

    return '127.0.0.1'


def get_public_ipv6():
    try:
        resp = requests.get('http://api6.ipify.org/', timeout=5).text.strip()
        if ipaddress.IPv6Address(resp).is_global:
            return '[%s]' % resp
    except Exception:
        pass

    try:
        resp = requests.get('http://ipv6.icanhazip.com/', timeout=5).text.strip()
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
