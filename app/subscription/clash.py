import copy
import json
from random import choice
from uuid import UUID

import yaml
from jinja2.exceptions import TemplateNotFound

from app.subscription.funcs import get_grpc_gun
from app.templates import render_template
from app.utils.helpers import yml_uuid_representer
from config import (
    CLASH_SETTINGS_TEMPLATE,
    CLASH_SUBSCRIPTION_TEMPLATE,
    MUX_TEMPLATE,
    USER_AGENT_TEMPLATE,
)

# Mihomo XMUX (reuse-settings) field mapping — Xray camelCase → mihomo kebab-case.
_XMUX_FIELD_MAP = (
    ("maxConcurrency", "max-concurrency"),
    ("maxConnections", "max-connections"),
    ("cMaxReuseTimes", "c-max-reuse-times"),
    ("hMaxRequestTimes", "h-max-request-times"),
    ("hMaxReusableSecs", "h-max-reusable-secs"),
    ("hKeepAlivePeriod", "h-keep-alive-period"),
)

# Transports with no mihomo/sing-box client equivalent — skipped on export.
_UNSUPPORTED_CLIENT_TRANSPORTS = frozenset({"kcp"})


def _host_first(host) -> str:
    if isinstance(host, list):
        return str(host[0]) if host else ""
    return str(host or "")


def _mihomo_range_value(val):
    if val is None or val == "" or val == 0:
        return None
    return str(val) if not isinstance(val, str) else val


def _xmux_to_reuse_settings(xmux: dict) -> dict | None:
    if not isinstance(xmux, dict) or not xmux:
        return None
    reuse = {}
    for xray_key, mihomo_key in _XMUX_FIELD_MAP:
        val = _mihomo_range_value(xmux.get(xray_key))
        if val is not None:
            reuse[mihomo_key] = val
    return reuse or None


def build_mihomo_xhttp_opts(inbound: dict) -> dict:
    """Map Xray xhttp/splithttp stream settings to mihomo *http-opts blocks."""
    path = inbound.get("path") or "/"
    opts: dict = {"path": path}
    host = _host_first(inbound.get("host"))
    if host:
        opts["host"] = host

    mode = inbound.get("mode") or "auto"
    if mode:
        opts["mode"] = mode

    if inbound.get("xPaddingBytes"):
        opts["x-padding-bytes"] = inbound["xPaddingBytes"]
    if inbound.get("noGRPCHeader"):
        opts["no-grpc-header"] = True
    if inbound.get("noSSEHeader"):
        opts["no-sse-header"] = True

    sc_max = inbound.get("scMaxEachPostBytes")
    if sc_max:
        opts["sc-max-each-post-bytes"] = sc_max
    sc_min = inbound.get("scMinPostsIntervalMs")
    if sc_min is not None and sc_min != "":
        opts["sc-min-posts-interval-ms"] = sc_min

    uplink = inbound.get("uplinkHTTPMethod")
    if uplink:
        opts["uplink-http-method"] = uplink

    reuse = _xmux_to_reuse_settings(inbound.get("xmux") or {})
    if reuse:
        opts["reuse-settings"] = reuse

    dl = inbound.get("downloadSettings")
    if isinstance(dl, dict) and dl:
        dl_src = {k: v for k, v in {**inbound, **dl}.items() if k != "downloadSettings"}
        dl_opts = build_mihomo_xhttp_opts(dl_src)
        dl_opts.pop("download-settings", None)
        if dl_opts:
            opts["download-settings"] = dl_opts

    return opts


class ClashConfiguration(object):
    def __init__(self):
        self.data = {
            'proxies': [],
            'proxy-groups': [],
            # Some clients rely on "rules" option and will fail without it.
            'rules': []
        }
        self.proxy_remarks = []
        self.mux_template = render_template(MUX_TEMPLATE)
        user_agent_data = json.loads(render_template(USER_AGENT_TEMPLATE))

        if 'list' in user_agent_data and isinstance(user_agent_data['list'], list):
            self.user_agent_list = user_agent_data['list']
        else:
            self.user_agent_list = []

        try:
            self.settings = yaml.load(render_template(CLASH_SETTINGS_TEMPLATE), Loader=yaml.SafeLoader)
        except TemplateNotFound:
            self.settings = {}

        del user_agent_data

    def render(self, reverse=False):
        if reverse:
            self.data['proxies'].reverse()

        yaml.add_representer(UUID, yml_uuid_representer)
        return yaml.dump(
            yaml.load(
                render_template(
                    CLASH_SUBSCRIPTION_TEMPLATE,
                    {"conf": self.data, "proxy_remarks": self.proxy_remarks}
                ),
                Loader=yaml.SafeLoader

            ),
            sort_keys=False,
            allow_unicode=True,
        )

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return self.render()

    def _remark_validation(self, remark):
        if not remark in self.proxy_remarks:
            return remark
        c = 2
        while True:
            new = f'{remark} ({c})'
            if not new in self.proxy_remarks:
                return new
            c += 1

    def http_config(
            self,
            path="",
            host="",
            random_user_agent: bool = False,
    ):
        config = copy.deepcopy(self.settings.get("http-opts", {
            'headers': {}
        }))

        if path:
            config["path"] = [path]
        if host:
            config["Host"] = host
        if random_user_agent:
            if "headers" not in config:
                config["headers"] = {}
            config["headers"]["User-Agent"] = choice(self.user_agent_list)

        return config

    def ws_config(
            self,
            path="",
            host="",
            max_early_data=None,
            early_data_header_name="",
            is_httpupgrade: bool = False,
            random_user_agent: bool = False,
    ):
        config = copy.deepcopy(self.settings.get("ws-opts", {}))
        if (host or random_user_agent) and "headers" not in config:
            config["headers"] = {}
        if path:
            config["path"] = path
        if host:
            config["headers"]["Host"] = host
        if random_user_agent:
            config["headers"]["User-Agent"] = choice(self.user_agent_list)
        if max_early_data and not is_httpupgrade:
            config["max-early-data"] = max_early_data
            config["early-data-header-name"] = early_data_header_name
        if is_httpupgrade:
            config["v2ray-http-upgrade"] = True
            config["v2ray-http-upgrade-fast-open"] = True

        return config

    def grpc_config(self, path=""):
        config = copy.deepcopy(self.settings.get("grpc-opts", {}))
        if path:
            config["grpc-service-name"] = path

        return config

    def h2_config(self, path="", host=""):
        config = copy.deepcopy(self.settings.get("h2-opts", {}))
        if path:
            config["path"] = path
        if host:
            config["host"] = [host]

        return config

    def tcp_config(self, path="", host=""):
        config = copy.deepcopy(self.settings.get("tcp-opts", {}))
        if path:
            config["path"] = [path]
        if host:
            if "headers" not in config:
                config["headers"] = {}
            config["headers"]["Host"] = host

        return config

    def make_node(self,
                  name: str,
                  remark: str,
                  type: str,
                  server: str,
                  port: int,
                  network: str,
                  tls: bool,
                  sni: str,
                  host: str,
                  path: str,
                  headers: str = '',
                  udp: bool = True,
                  alpn: str = '',
                  ais: bool = '',
                  mux_enable: bool = False,
                  random_user_agent: bool = False,
                  ip_version: str = ""):

        if network in ["grpc", "gun"]:
            path = get_grpc_gun(path)

        if type == 'shadowsocks':
            type = 'ss'
        if network in ("http", "h2", "h3"):
            network = "h2"
        if network in ('tcp', 'raw') and headers == 'http':
            network = 'http'
        if network == 'httpupgrade':
            network = 'ws'
            is_httpupgrade = True
        else:
            is_httpupgrade = False
        node = {
            'name': remark,
            'type': type,
            'server': server,
            'port': port,
            'network': network,
            'udp': udp
        }

        if "?ed=" in path:
            path, max_early_data = path.split("?ed=")
            max_early_data, = max_early_data.split("/")
            max_early_data = int(max_early_data)
            early_data_header_name = "Sec-WebSocket-Protocol"
        else:
            max_early_data = None
            early_data_header_name = ""

        if type == 'ss':  # shadowsocks
            return node

        if tls:
            node['tls'] = True
            if type == 'trojan':
                node['sni'] = sni
            else:
                node['servername'] = sni
            if alpn:
                node['alpn'] = alpn.split(',')
            if ais:
                node['skip-cert-verify'] = ais

        if network == 'http':
            net_opts = self.http_config(
                path=path,
                host=host,
                random_user_agent=random_user_agent,
            )

        elif network == 'ws':
            net_opts = self.ws_config(
                path=path,
                host=host,
                max_early_data=max_early_data,
                early_data_header_name=early_data_header_name,
                is_httpupgrade=is_httpupgrade,
                random_user_agent=random_user_agent,
            )

        elif network == 'grpc' or network == 'gun':
            net_opts = self.grpc_config(path=path)

        elif network == 'h2':
            net_opts = self.h2_config(path=path, host=host)

        elif network in ('tcp', 'raw'):
            net_opts = self.tcp_config(path=path, host=host)

        else:
            net_opts = {}

        node[f'{network}-opts'] = net_opts

        mux_json = json.loads(self.mux_template)
        mux_config = mux_json["clash"]

        if mux_enable:
            node['smux'] = mux_config
        if ip_version:
            node['ip-version'] = ip_version

        return node

    def add(self, remark: str, address: str, inbound: dict, settings: dict):
        # Standard Clash: no kcp / splithttp / xhttp transports.
        if inbound['network'] in ("kcp", "splithttp", "xhttp"):
            return

        proxy_remark = self._remark_validation(remark)

        node = self.make_node(
            name=remark,
            remark=proxy_remark,
            type=inbound['protocol'],
            server=address,
            port=inbound['port'],
            network=inbound['network'],
            tls=(inbound['tls'] == 'tls'),
            sni=inbound['sni'],
            host=inbound['host'],
            path=inbound['path'],
            headers=inbound['header_type'],
            udp=True,
            alpn=inbound.get('alpn', ''),
            ais=inbound.get('ais', False),
            mux_enable=inbound.get('mux_enable', False),
            random_user_agent=inbound.get("random_user_agent"),
            ip_version=inbound.get("mihomo_ip_version") or "",
        )

        if inbound['protocol'] == 'vmess':
            node['uuid'] = settings['id']
            node['alterId'] = 0
            node['cipher'] = 'auto'

        elif inbound['protocol'] == 'trojan':
            node['password'] = settings['password']

        elif inbound['protocol'] == 'shadowsocks':
            method = settings['method']
            password = settings['password']
            if str(method).startswith("2022-"):
                server_key = inbound.get("ss_password")
                if not server_key:
                    return
                method = inbound.get("ss_method") or method
                password = f"{server_key}:{password}"
            node['password'] = password
            node['cipher'] = method

        else:
            return

        self.data['proxies'].append(node)
        self.proxy_remarks.append(proxy_remark)


class ClashMetaConfiguration(ClashConfiguration):
    def make_node(self,
                  name: str,
                  remark: str,
                  type: str,
                  server: str,
                  port: int,
                  network: str,
                  tls: bool,
                  sni: str,
                  host: str,
                  path: str,
                  headers: str = '',
                  udp: bool = True,
                  alpn: str = '',
                  fp: str = '',
                  pbk: str = '',
                  sid: str = '',
                  ais: bool = '',
                  mux_enable: bool = False,
                  random_user_agent: bool = False,
                  ip_version: str = ""):
        node = super().make_node(
            name=name,
            remark=remark,
            type=type,
            server=server,
            port=port,
            network=network,
            tls=tls,
            sni=sni,
            host=host,
            path=path,
            headers=headers,
            udp=udp,
            alpn=alpn,
            ais=ais,
            mux_enable=mux_enable,
            random_user_agent=random_user_agent,
            ip_version=ip_version,
        )
        if fp:
            node['client-fingerprint'] = fp
        if pbk:
            node['reality-opts'] = {"public-key": pbk, "short-id": sid}

        return node

    def add(self, remark: str, address: str, inbound: dict, settings: dict):
        net = inbound['network']
        # mKCP has no clash-meta client transport — skip (core limitation).
        if net in _UNSUPPORTED_CLIENT_TRANSPORTS or (net == "quic" and inbound["header_type"] != "none"):
            return
        # mihomo xhttp/splithttp outbound — VLESS only (see mihomo transport docs).
        if net in ("xhttp", "splithttp") and inbound['protocol'] != 'vless':
            return

        proxy_remark = self._remark_validation(remark)

        node = self.make_node(
            name=remark,
            remark=proxy_remark,
            type=inbound['protocol'],
            server=address,
            port=inbound['port'],
            network=inbound['network'],
            tls=(inbound['tls'] in ('tls', 'reality')),
            sni=inbound['sni'],
            host=inbound['host'],
            path=inbound['path'],
            headers=inbound['header_type'],
            udp=True,
            alpn=inbound.get('alpn', ''),
            fp=inbound.get('fp', ''),
            pbk=inbound.get('pbk', ''),
            sid=inbound.get('sid', ''),
            ais=inbound.get('ais', False),
            mux_enable=inbound.get('mux_enable', False),
            random_user_agent=inbound.get("random_user_agent"),
            ip_version=inbound.get("mihomo_ip_version") or "",
        )

        if net in ("xhttp", "splithttp"):
            node[f"{net}-opts"] = build_mihomo_xhttp_opts(inbound)

        if inbound['protocol'] == 'vmess':
            node['uuid'] = settings['id']
            node['alterId'] = 0
            node['cipher'] = 'auto'

        elif inbound['protocol'] == 'vless':
            node['uuid'] = settings['id']

            if inbound['network'] in ('tcp', 'raw', 'kcp') and inbound['header_type'] != 'http' and inbound['tls'] != 'none':
                node['flow'] = settings.get('flow', '')

        elif inbound['protocol'] == 'trojan':
            node['password'] = settings['password']

        elif inbound['protocol'] == 'shadowsocks':
            method = settings['method']
            password = settings['password']
            if str(method).startswith("2022-"):
                server_key = inbound.get("ss_password")
                if not server_key:
                    return
                method = inbound.get("ss_method") or method
                password = f"{server_key}:{password}"
            node['password'] = password
            node['cipher'] = method

        else:
            return

        self.data['proxies'].append(node)
        self.proxy_remarks.append(proxy_remark)
