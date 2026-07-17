import grpc

from .base import XRayBase
from .exceptions import RelatedError
from .proto.app.proxyman.command import command_pb2, command_pb2_grpc
from .proto.common.protocol import user_pb2
from .types.account import Account
from .types.message import Message, TypedMessage

try:
    from .proto.core import config_pb2 as core_config_pb2
except ModuleNotFoundError:
    from .proto import config_pb2 as core_config_pb2


class Proxyman(XRayBase):
    def alter_inbound(self, tag: str, operation: TypedMessage, timeout: int = None) -> bool:
        stub = command_pb2_grpc.HandlerServiceStub(self._channel)
        try:
            stub.AlterInbound(command_pb2.AlterInboundRequest(tag=tag, operation=operation), timeout=timeout)
            return True

        except grpc.RpcError as e:
            raise RelatedError(e)

    def alter_outbound(self, tag: str, operation: TypedMessage, timeout: int = None) -> bool:
        stub = command_pb2_grpc.HandlerServiceStub(self._channel)
        try:
            stub.AlterInbound(command_pb2.AlterOutboundRequest(tag=tag, operation=operation), timeout=timeout)
            return True

        except grpc.RpcError as e:
            raise RelatedError(e)

    def add_inbound_user(self, tag: str, user: Account, timeout: int = None) -> bool:
        return self.alter_inbound(
            tag=tag,
            operation=Message(
                command_pb2.AddUserOperation(
                    user=user_pb2.User(
                        level=user.level,
                        email=user.email,
                        account=user.message
                    )
                )
            ), timeout=timeout)

    def remove_inbound_user(self, tag: str, email: str, timeout: int = None) -> bool:
        return self.alter_inbound(
            tag=tag,
            operation=Message(
                command_pb2.RemoveUserOperation(
                    email=email
                )
            ), timeout=timeout)

    def add_outbound_user(self, tag: str, user: Account, timeout: int = None) -> bool:
        return self.alter_outbound(
            tag=tag,
            operation=Message(
                command_pb2.AddUserOperation(
                    user=user_pb2.User(
                        level=user.level,
                        email=user.email,
                        account=user.message
                    )
                )
            ), timeout=timeout)

    def remove_outbound_user(self, tag: str, email: str, timeout: int = None) -> bool:
        return self.alter_outbound(
            tag=tag,
            operation=Message(
                command_pb2.RemoveUserOperation(
                    email=email
                )
            ), timeout=timeout)

    def add_inbound(self, inbound, timeout: int = None) -> bool:
        """Hot-add an inbound handler to the running core.

        ``inbound`` must be a serialized ``core.InboundHandlerConfig`` protobuf.
        Only inbounds whose proxy/stream settings have Python protos here can be
        built this way — custom stream transports (e.g. Finalmask) cannot; for
        those use the node agent's ``xray api adi`` path
        (node/xray.py::hot_replace_inbounds), where the CLI builds the typed
        config from JSON itself.
        """
        stub = command_pb2_grpc.HandlerServiceStub(self._channel)
        try:
            stub.AddInbound(command_pb2.AddInboundRequest(inbound=inbound), timeout=timeout)
            return True

        except grpc.RpcError as e:
            raise RelatedError(e)

    def remove_inbound(self, tag: str, timeout: int = None) -> bool:
        """Hot-remove an inbound handler (by tag) from the running core."""
        stub = command_pb2_grpc.HandlerServiceStub(self._channel)
        try:
            stub.RemoveInbound(command_pb2.RemoveInboundRequest(tag=tag), timeout=timeout)
            return True

        except grpc.RpcError as e:
            raise RelatedError(e)

    def add_outbound(self):
        raise NotImplementedError

    def remove_outbound(self):
        raise NotImplementedError
