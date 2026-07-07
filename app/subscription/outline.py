import json


class OutlineConfiguration:
    def __init__(self):
        self.config = {}

    def add_directly(self, data: dict):
        self.config.update(data)

    def render(self, reverse=False):
        if reverse:
            items = list(self.config.items())
            items.reverse()
            self.config = dict(items)
        return json.dumps(self.config, indent=0)

    def make_outbound(
        self, remark: str, address: str, port: int, password: str, method: str
    ):
        config = {
            "method": method,
            "password": password,
            "server": address,
            "server_port": port,
            "tag": remark,
        }
        return config

    def add(self, remark: str, address: str, inbound: dict, settings: dict, **kwargs):
        if inbound["protocol"] != "shadowsocks":
            return

        method = settings["method"]
        password = settings["password"]
        if str(method).startswith("2022-"):
            server_key = inbound.get("ss_password")
            if not server_key:
                return
            method = inbound.get("ss_method") or method
            password = f"{server_key}:{password}"

        outbound = self.make_outbound(
            remark=remark,
            address=address,
            port=inbound["port"],
            password=password,
            method=method,
        )
        self.add_directly(outbound)