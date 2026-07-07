"""Bandwidth unit helpers (UI stores Mbps; Xray policy uses bytes/sec)."""


def mbps_to_bytes_per_sec(mbps: int) -> int:
    """Convert megabits per second (decimal Mbps) to bytes per second."""
    if mbps <= 0:
        return 0
    return int(mbps * 1_000_000 // 8)
