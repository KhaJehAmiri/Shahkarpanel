"""Query sing-box V2Ray API user traffic counters (gRPC, Xray-compatible)."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict

import grpc

try:
    from stats_proto import command_pb2, command_pb2_grpc
except ImportError:  # pytest imports via ``node`` package
    from node.stats_proto import command_pb2, command_pb2_grpc


def query_user_transfer(host: str, port: int, *, reset: bool = True, timeout: float = 5.0) -> Dict[str, dict]:
    """Return ``{user_name: {"rx", "tx"}}`` interval bytes (downlink/uplink).

    Uses ``QueryStats(pattern="user>>>", reset=True)`` — same contract as the
    panel's Xray usage job.
    """
    channel = grpc.insecure_channel(f"{host}:{port}")
    try:
        stub = command_pb2_grpc.StatsServiceStub(channel)
        resp = stub.query_stats(
            command_pb2.QueryStatsRequest(pattern="user>>>", reset=reset),
            timeout=timeout,
        )
    except grpc.RpcError:
        return {}
    finally:
        channel.close()

    down: dict[str, int] = defaultdict(int)
    up: dict[str, int] = defaultdict(int)
    for stat in resp.stat:
        parts = stat.name.split(">>>")
        if len(parts) < 4 or parts[0] != "user":
            continue
        name, link = parts[1], parts[3]
        if link == "downlink":
            down[name] += int(stat.value)
        elif link == "uplink":
            up[name] += int(stat.value)

    out: Dict[str, dict] = {}
    for name in set(down) | set(up):
        rx, tx = down[name], up[name]
        if rx or tx:
            out[name] = {"rx": rx, "tx": tx}
    return out
