import grpc


class XRayBase(object):
    def __init__(self, address: str, port: int, ssl_cert: str = None, ssl_target_name: str = None):
        if ssl_cert is None:
            self.address = address
            self.port = port
            self._channel = grpc.insecure_channel(f"{address}:{port}")

        else:
            self.address = address
            self.port = port
            creds = grpc.ssl_channel_credentials(root_certificates=ssl_cert)
            opts = (('grpc.ssl_target_name_override', ssl_target_name,),) if ssl_target_name else ()
            self._channel = grpc.secure_channel(f"{address}:{port}",
                                                credentials=creds,
                                                options=opts)

    def close(self) -> None:
        channel = getattr(self, "_channel", None)
        if channel is None:
            return
        try:
            channel.close()
        except Exception:
            pass
        self._channel = None
