# Minimal gRPC stub for sing-box / Xray-compatible stats messages.
import grpc

try:
    from stats_proto import command_pb2
except ImportError:
    from node.stats_proto import command_pb2

# sing-box renames its service at init() to v2ray.core.app.stats.command.StatsService.
_SINGBOX_QUERY_STATS = "/v2ray.core.app.stats.command.StatsService/QueryStats"
_XRAY_QUERY_STATS = "/xray.app.stats.command.StatsService/QueryStats"


class StatsServiceStub:
    def __init__(self, channel):
        self._channel = channel
        self._query_stats_singbox = channel.unary_unary(
            _SINGBOX_QUERY_STATS,
            request_serializer=command_pb2.QueryStatsRequest.SerializeToString,
            response_deserializer=command_pb2.QueryStatsResponse.FromString,
        )
        self._query_stats_xray = channel.unary_unary(
            _XRAY_QUERY_STATS,
            request_serializer=command_pb2.QueryStatsRequest.SerializeToString,
            response_deserializer=command_pb2.QueryStatsResponse.FromString,
        )

    def query_stats(self, request, timeout=None):
        """QueryStats — sing-box path first, legacy Xray-core path as fallback."""
        try:
            return self._query_stats_singbox(request, timeout=timeout)
        except grpc.RpcError as exc:
            if exc.code() != grpc.StatusCode.UNIMPLEMENTED:
                raise
            return self._query_stats_xray(request, timeout=timeout)
