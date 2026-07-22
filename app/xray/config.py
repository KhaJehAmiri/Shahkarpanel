from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import PosixPath
from typing import Union

import commentjson

from app.db import GetDB
from app.db import models as db_models
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.utils.crypto import get_cert_SANs
from app.xray.inbound_normalize import NXPANEL_INBOUND_KIND
from app.xray.network_defaults import DEFAULT_TLS_FINGERPRINT, effective_vless_flow
from config import DEBUG, XRAY_EXCLUDE_INBOUND_TAGS, XRAY_FALLBACKS_INBOUND_TAG


def merge_dicts(a, b):  # B will override A dictionary key and values
    for key, value in b.items():
        if isinstance(value, dict) and key in a and isinstance(a[key], dict):
            merge_dicts(a[key], value)  # Recursively merge nested dictionaries
        else:
            a[key] = value
    return a


class XRayConfig(dict):
    def __init__(self,
                 config: Union[dict, str, PosixPath] = {},
                 api_host: str = "127.0.0.1",
                 api_port: int = 8080):
        if isinstance(config, str):
            try:
                # considering string as json
                config = commentjson.loads(config)
            except (json.JSONDecodeError, ValueError):
                # considering string as file path
                with open(config, 'r') as file:
                    config = commentjson.loads(file.read())

        if isinstance(config, PosixPath):
            with open(config, 'r') as file:
                config = commentjson.loads(file.read())

        if isinstance(config, dict):
            config = deepcopy(config)

        self.api_host = api_host
        self.api_port = api_port

        super().__init__(config)
        self._normalize_shape()
        self._sanitize_outbounds()
        self._validate()

        self.inbounds = []
        self.inbounds_by_protocol = {}
        self.inbounds_by_tag = {}
        self._fallbacks_inbound = self.get_inbound(XRAY_FALLBACKS_INBOUND_TAG)
        self._resolve_inbounds()

        self._apply_api()

    def _apply_api(self):
        forced_policies = {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                    # Concurrent source-IP count per user (subscribe "online devices").
                    "statsUserOnline": True,
                }
            },
            "system": {
                # Inbound counters power Home "Overall Speed" (fleet panel+nodes)
                # without racing record_node_usages, which resets outbound stats.
                "statsInboundDownlink": True,
                "statsInboundUplink": True,
                "statsOutboundDownlink": True,
                "statsOutboundUplink": True
            }
        }
        if self.get("policy"):
            self["policy"] = merge_dicts(self.get("policy"), forced_policies)
        else:
            self["policy"] = forced_policies

        self["api"] = {
            "services": [
                "HandlerService",
                "StatsService",
                "LoggerService"
            ],
            "tag": "API"
        }
        self["stats"] = {}

        api_inbound = self.get_inbound("API_INBOUND")
        if api_inbound:
            api_inbound["listen"] = self.api_host
            api_inbound["port"] = self.api_port
            api_inbound.setdefault("settings", {})["address"] = self.api_host
        else:
            inbound = {
                "listen": self.api_host,
                "port": self.api_port,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": self.api_host
                },
                "tag": "API_INBOUND"
            }
            try:
                self["inbounds"].insert(0, inbound)
            except KeyError:
                self["inbounds"] = []
                self["inbounds"].insert(0, inbound)

        rule = {
            "inboundTag": [
                "API_INBOUND"
            ],
            "outboundTag": "API",
            "type": "field"
        }
        routing = self.get("routing")
        if not isinstance(routing, dict):
            routing = {"domainStrategy": "IPIfNonMatch", "rules": []}
            self["routing"] = routing
        rules = routing.setdefault("rules", [])
        if not isinstance(rules, list):
            rules = []
            routing["rules"] = rules
        if not any(
            isinstance(r, dict)
            and r.get("outboundTag") == "API"
            and "API_INBOUND" in (r.get("inboundTag") or [])
            for r in rules
        ):
            rules.insert(0, rule)

    def _normalize_shape(self) -> None:
        """Accept legacy/partial configs (missing keys, null lists) after users clear inbounds."""
        if not isinstance(self.get("inbounds"), list):
            self["inbounds"] = []

        outbounds = self.get("outbounds")
        if not isinstance(outbounds, list) or not outbounds:
            self["outbounds"] = [
                {"protocol": "freedom", "tag": "DIRECT"},
                {"protocol": "blackhole", "tag": "BLOCK"},
            ]

        routing = self.get("routing")
        if not isinstance(routing, dict):
            self["routing"] = {"domainStrategy": "IPIfNonMatch", "rules": []}
        elif not isinstance(routing.get("rules"), list):
            routing["rules"] = []

    def _sanitize_outbounds(self):
        valid_wg_ds = {
            "", "ForceIP", "ForceIPv4", "ForceIPv6", "ForceIPv6v4", "ForceIPv4v6",
        }
        for outbound in self.get("outbounds") or []:
            if outbound.get("protocol") != "wireguard":
                continue
            settings = outbound.get("settings") or {}
            ds = settings.get("domainStrategy")
            if ds is not None and ds not in valid_wg_ds:
                settings = dict(settings)
                settings.pop("domainStrategy", None)
                outbound["settings"] = settings

    def _validate(self):
        if not self.get("outbounds"):
            raise ValueError("config doesn't have outbounds")

        # Fresh installs ship with no user inbounds; API_INBOUND is injected in
        # _apply_api() after validation.
        for inbound in self.get("inbounds") or []:
            if not inbound.get("tag"):
                raise ValueError("all inbounds must have a unique tag")
            if ',' in inbound.get("tag"):
                raise ValueError("character «,» is not allowed in inbound tag")
        for outbound in self['outbounds']:
            if not outbound.get("tag"):
                raise ValueError("all outbounds must have a unique tag")
            if ',' in outbound.get("tag"):
                raise ValueError("character «,» is not allowed in outbound tag")

        tags = [o.get("tag") for o in self['outbounds']]
        if len(tags) != len(set(tags)):
            raise ValueError("duplicate outbound tags are not allowed")

    def _resolve_inbounds(self):
        for inbound in self.get("inbounds") or []:
            raw_proto = str(inbound.get('protocol') or '').lower()
            if raw_proto == 'amneziawg':
                inbound['protocol'] = ProxyTypes.WireGuard.value
                settings_raw = inbound.setdefault('settings', {})
                settings_raw.setdefault(NXPANEL_INBOUND_KIND, 'amneziawg')

            if inbound['protocol'] not in ProxyTypes._value2member_map_:
                continue

            # Plain WireGuard Xray listeners are server-only. AmneziaWG-marked
            # wireguard inbounds are assignable product inbounds (peers injected
            # in include_db_users). Native WG nodes use a separate code path.
            is_xray_awg = self._is_xray_amnezia_inbound(inbound)
            if inbound['protocol'] == ProxyTypes.WireGuard.value and not is_xray_awg:
                continue

            if inbound['tag'] in XRAY_EXCLUDE_INBOUND_TAGS:
                continue

            if not inbound.get('settings'):
                inbound['settings'] = {}
            if not inbound['settings'].get('clients'):
                inbound['settings']['clients'] = []

            settings = {
                "tag": inbound["tag"],
                "protocol": inbound["protocol"],
                "port": None,
                "network": "tcp",
                "tls": 'none',
                "sni": [],
                "host": [],
                "path": "",
                "header_type": "",
                "is_fallback": False
            }

            # Shadowsocks-2022 multi-user needs the inbound's server PSK + method
            # to assemble client links (password = serverKey:userKey).
            if inbound['protocol'] == ProxyTypes.Shadowsocks.value:
                settings['ss_method'] = inbound['settings'].get('method')
                settings['ss_password'] = inbound['settings'].get('password')

            # VLESS Encryption: client outbound string is stored alongside inbound
            # settings (xray ignores it server-side; subscription uses it).
            if inbound['protocol'] == ProxyTypes.VLESS.value:
                raw_settings = inbound.get('settings') or {}
                dec = str(raw_settings.get('decryption') or 'none')
                enc = str(raw_settings.get('encryption') or '')
                if dec not in ('', 'none') and enc and enc not in ('', 'none'):
                    settings['vless_encryption'] = enc

            # port settings
            try:
                settings['port'] = inbound['port']
            except KeyError:
                if self._fallbacks_inbound:
                    try:
                        settings['port'] = self._fallbacks_inbound['port']
                        settings['is_fallback'] = True
                    except KeyError:
                        raise ValueError("fallbacks inbound doesn't have port")

            # stream settings
            if stream := inbound.get('streamSettings'):
                net = stream.get('network', 'tcp')
                net_settings = stream.get(f"{net}Settings", {})
                security = stream.get("security")
                tls_settings = stream.get(f"{security}Settings")

                if settings['is_fallback'] is True:
                    # probably this is a fallback
                    security = self._fallbacks_inbound.get(
                        'streamSettings', {}).get('security')
                    tls_settings = self._fallbacks_inbound.get(
                        'streamSettings', {}).get(f"{security}Settings", {})

                settings['network'] = net

                if security == 'tls':
                    settings['tls'] = 'tls'
                    if isinstance(tls_settings, dict):
                        from app.subscription.tls_client import analyze_inbound_tls

                        tls_meta = analyze_inbound_tls(tls_settings)
                        settings['tls_server_name'] = tls_meta['tls_server_name']
                        settings['cert_sans'] = tls_meta['cert_sans']
                        settings['cert_pin_sha256'] = tls_meta['cert_pin_sha256']
                        settings['cert_self_signed'] = tls_meta['cert_self_signed']
                        if tls_meta['ech_config_list']:
                            settings['ech_config_list'] = tls_meta['ech_config_list']

                        fp = tls_settings.get('fingerprint')
                        settings['fp'] = fp or DEFAULT_TLS_FINGERPRINT
                        alpn = tls_settings.get('alpn')
                        if alpn:
                            if isinstance(alpn, list):
                                settings['alpn'] = ','.join(str(x) for x in alpn if x)
                            else:
                                settings['alpn'] = str(alpn)
                    for certificate in tls_settings.get('certificates', []):

                        if certificate.get("certificateFile", None):
                            try:
                                with open(certificate['certificateFile'], 'rb') as file:
                                    cert = file.read()
                                    settings['sni'].extend(get_cert_SANs(cert))
                            except OSError:
                                pass

                        if certificate.get("certificate", None):
                            cert = certificate['certificate']
                            if isinstance(cert, list):
                                cert = '\n'.join(cert)
                            if isinstance(cert, str):
                                cert = cert.encode()
                            settings['sni'].extend(get_cert_SANs(cert))

                    server_name = str(tls_settings.get('serverName') or '').strip()
                    if server_name and server_name not in settings['sni']:
                        settings['sni'].insert(0, server_name)

                    settings['sni'] = [str(s) for s in settings['sni']]

                elif security == 'reality':
                    rs_settings = tls_settings.get('settings') or {}
                    settings['fp'] = (
                        rs_settings.get('fingerprint')
                        or tls_settings.get('fingerprint')
                        or 'chrome'
                    )
                    settings['tls'] = 'reality'
                    settings['sni'] = tls_settings.get('serverNames', [])

                    try:
                        settings['pbk'] = tls_settings['publicKey']
                    except KeyError:
                        pbk = rs_settings.get('publicKey')
                        if pbk:
                            settings['pbk'] = pbk
                        else:
                            pvk = tls_settings.get('privateKey')
                            if not pvk:
                                raise ValueError(
                                    f"You need to provide privateKey in realitySettings of {inbound['tag']}")

                            try:
                                from app.xray import core
                                x25519 = core.get_x25519(pvk)
                                settings['pbk'] = x25519['public_key']
                            except ImportError:
                                pass

                            if not settings.get('pbk'):
                                raise ValueError(
                                    f"You need to provide publicKey in realitySettings of {inbound['tag']}")

                    try:
                        settings['sids'] = tls_settings.get('shortIds')
                        settings['sids'][0]  # check if there is any shortIds
                    except (IndexError, TypeError):
                        raise ValueError(
                            f"You need to define at least one shortID in realitySettings of {inbound['tag']}")
                    settings['spx'] = (
                        rs_settings.get('spiderX')
                        or tls_settings.get('spiderX')
                        or tls_settings.get('SpiderX')
                        or ""
                    )

                if net in ('tcp', 'raw'):
                    header = net_settings.get('header', {})
                    request = header.get('request', {})
                    path = request.get('path')
                    host = request.get('headers', {}).get('Host')

                    settings['header_type'] = header.get('type', '')

                    if isinstance(path, str) or isinstance(host, str):
                        raise ValueError(f"Settings of {inbound['tag']} for path and host must be list, not str\n"
                                         "https://xtls.github.io/config/transports/tcp.html#httpheaderobject")

                    if path and isinstance(path, list):
                        settings['path'] = path[0]

                    if host and isinstance(host, list):
                        settings['host'] = host

                elif net == 'ws':
                    path = net_settings.get('path', '')
                    host = net_settings.get('host', '') or net_settings.get('headers', {}).get('Host')

                    settings['header_type'] = ''

                    if isinstance(path, list) or isinstance(host, list):
                        raise ValueError(f"Settings of {inbound['tag']} for path and host must be str, not list\n"
                                         "https://xtls.github.io/config/transports/websocket.html#websocketobject")

                    if isinstance(path, str):
                        settings['path'] = path

                    if isinstance(host, str):
                        settings['host'] = [host]

                    settings["heartbeatPeriod"] = net_settings.get('heartbeatPeriod', 0)
                elif net == 'grpc' or net == 'gun':
                    settings['header_type'] = ''
                    settings['path'] = net_settings.get('serviceName', '')
                    host = net_settings.get('authority', '')
                    settings['host'] = [host]
                    settings['multiMode'] = net_settings.get('multiMode', False)

                elif net == 'quic':
                    settings['header_type'] = net_settings.get('header', {}).get('type', '')
                    settings['path'] = net_settings.get('key', '')
                    settings['host'] = [net_settings.get('security', '')]

                elif net == 'httpupgrade':
                    settings['path'] = net_settings.get('path', '')
                    host = net_settings.get('host', '')
                    settings['host'] = [host]

                elif net in ('splithttp', 'xhttp'):
                    settings['path'] = net_settings.get('path', '')
                    host = net_settings.get('host', '')
                    settings['host'] = [host]
                    settings['scMaxEachPostBytes'] = net_settings.get('scMaxEachPostBytes', 1000000)
                    if net_settings.get('scMaxBufferedPosts') is not None:
                        settings['scMaxBufferedPosts'] = net_settings.get('scMaxBufferedPosts')
                    settings['scMaxConcurrentPosts'] = net_settings.get('scMaxConcurrentPosts', 100)
                    settings['scMinPostsIntervalMs'] = net_settings.get('scMinPostsIntervalMs', 30)
                    settings['xPaddingBytes'] = net_settings.get('xPaddingBytes', "100-1000")
                    settings['xmux'] = net_settings.get('xmux', {})
                    settings["mode"] = net_settings.get("mode", "auto")
                    settings["noGRPCHeader"] = net_settings.get("noGRPCHeader", False)
                    settings["noSSEHeader"] = net_settings.get("noSSEHeader", False)
                    settings["keepAlivePeriod"] = net_settings.get("keepAlivePeriod", 0)
                    if net_settings.get("uplinkHTTPMethod"):
                        settings["uplinkHTTPMethod"] = net_settings.get("uplinkHTTPMethod")
                    if net_settings.get("scStreamUpServerSecs"):
                        settings["scStreamUpServerSecs"] = net_settings.get("scStreamUpServerSecs")
                    if net_settings.get("serverMaxHeaderBytes"):
                        settings["serverMaxHeaderBytes"] = net_settings.get("serverMaxHeaderBytes")
                    dl = net_settings.get("downloadSettings")
                    if isinstance(dl, dict) and dl:
                        settings["downloadSettings"] = dl

                elif net == 'kcp':
                    header = net_settings.get('header', {})

                    settings['header_type'] = header.get('type', '')
                    settings['host'] = header.get('domain', '')
                    settings['path'] = net_settings.get('seed', '')

                elif net in ("http", "h2", "h3"):
                    net_settings = stream.get("httpSettings", {})

                    settings['host'] = net_settings.get('host') or net_settings.get('Host', '')
                    settings['path'] = net_settings.get('path', '')

                else:
                    settings['path'] = net_settings.get('path', '')
                    host = net_settings.get(
                        'host', {}) or net_settings.get('Host', {})
                    if host and isinstance(host, str):
                        settings['host'] = host
                    elif host and isinstance(host, list):
                        settings['host'] = host[0]

            if is_xray_awg:
                settings["xray_awg"] = True
                settings["protocol"] = ProxyTypes.WireGuard.value
                api_key = "amneziawg"
            else:
                api_key = inbound["protocol"]

            self.inbounds.append(settings)
            self.inbounds_by_tag[inbound['tag']] = settings

            try:
                self.inbounds_by_protocol[api_key].append(settings)
            except KeyError:
                self.inbounds_by_protocol[api_key] = [settings]

    @staticmethod
    def _is_xray_amnezia_inbound(inbound: dict) -> bool:
        """True when a wireguard inbound is an assignable AmneziaWG product listener."""
        proto = str(inbound.get("protocol") or "").lower()
        settings = inbound.get("settings") or {}
        if settings.get(NXPANEL_INBOUND_KIND) == "amneziawg":
            return True
        if proto == "amneziawg":
            return True
        if proto == ProxyTypes.WireGuard.value:
            tag = str(inbound.get("tag") or "")
            if re.search(r"amnezia|awg", tag, re.I):
                return True
        return False

    def product_inbounds_for_type(self, proxy_type: ProxyTypes) -> list:
        """Inbounds a user proxy of ``proxy_type`` may be assigned to."""
        key = proxy_type.value if isinstance(proxy_type, ProxyTypes) else str(proxy_type)
        items = list(self.inbounds_by_protocol.get(key, []))
        if key == ProxyTypes.WireGuard.value:
            items.extend(self.inbounds_by_protocol.get("amneziawg", []))
        return items

    @staticmethod
    def _wg_subnet_from_settings(settings: dict) -> str:
        import ipaddress

        addrs = settings.get("address") or []
        if isinstance(addrs, str):
            addrs = [addrs]
        for raw in addrs:
            try:
                return str(ipaddress.ip_interface(str(raw)).network)
            except ValueError:
                continue
        return "10.8.0.0/24"

    def _inject_xray_awg_peers(self, config: "XRayConfig", grouped_data: dict) -> None:
        awg_inbounds = self.inbounds_by_protocol.get("amneziawg") or []
        if not awg_inbounds:
            return

        from app.wireguard.kind import wg_wants_awg_address
        from app.wireguard.pool import WireGuardPeerIPAllocator

        rows = grouped_data.get(ProxyTypes.WireGuard.value, [])
        for inbound_meta in awg_inbounds:
            tag = inbound_meta["tag"]
            raw = config.get_inbound(tag)
            if not raw:
                continue
            settings = raw.setdefault("settings", {})
            subnet = self._wg_subnet_from_settings(settings)
            peers = []
            used_addrs = []
            for _uid, _username, user_settings, excluded_tags in rows:
                if excluded_tags and tag in excluded_tags:
                    continue
                if not wg_wants_awg_address(user_settings or {}):
                    continue
                pub = (user_settings or {}).get("public_key")
                if not pub:
                    continue
                addr = (user_settings or {}).get("awg_address") or (user_settings or {}).get("address")
                if not addr:
                    allocator = WireGuardPeerIPAllocator(subnet, used=used_addrs)
                    addr = allocator.allocate()
                    if not addr:
                        continue
                used_addrs.append(addr)
                peers.append({"publicKey": pub, "allowedIPs": [addr]})
            settings["peers"] = peers

    def _apply_shadowsocks_speed_tiers(self, config: "XRayConfig", user_speed: dict) -> list:
        """Keep all SS clients on the base inbound; assign policy levels only.

        Per-tier listen ports + ``tc`` shaping are not used on the panel host:
        Docker lacks the privileges for traffic control, and separate SS2022
        inbounds on derived ports caused bind races and intermittent auth failures.
        """
        inbounds = config.get("inbounds") or []
        ss_tags = {m["tag"] for m in (self.inbounds_by_protocol.get(ProxyTypes.Shadowsocks.value) or [])}
        for tag in ss_tags:
            inbound = config.get_inbound(tag)
            if not inbound:
                continue
            settings = inbound.setdefault("settings", {})
            clients = list(settings.get("clients") or [])
            for client in clients:
                email = client.get("email") or ""
                try:
                    uid = int(str(email).split(".", 1)[0])
                except (TypeError, ValueError):
                    continue
                up, down = user_speed.get(uid, (None, None))
                if up or down:
                    client["level"] = (uid % 9000) + 100
            settings["clients"] = clients
        config["inbounds"] = inbounds
        return []

    def get_inbound(self, tag) -> dict:
        for inbound in self.get("inbounds") or []:
            if inbound['tag'] == tag:
                return inbound

    def get_outbound(self, tag) -> dict:
        for outbound in self.get("outbounds") or []:
            if outbound['tag'] == tag:
                return outbound

    def to_json(self, **json_kwargs):
        return json.dumps(self, **json_kwargs)

    def copy(self):
        return deepcopy(self)

    def include_db_users(self) -> XRayConfig:
        config = self.copy()

        with GetDB() as db:
            awg_inbounds = self.inbounds_by_protocol.get("amneziawg") or []
            if awg_inbounds:
                from app.db.models import Proxy
                from app.wireguard.kind import wg_wants_awg_address
                from app.wireguard.operations import ensure_user_address

                first = config.get_inbound(awg_inbounds[0]["tag"]) or {}
                subnet = self._wg_subnet_from_settings(first.get("settings") or {})
                for proxy in db.query(Proxy).filter(Proxy.type == ProxyTypes.WireGuard).all():
                    if wg_wants_awg_address(dict(proxy.settings or {})):
                        ensure_user_address(db, proxy, subnet)

            query = db.query(
                db_models.User.id,
                db_models.User.username,
                db_models.User.speed_limit_up,
                db_models.User.speed_limit_down,
                db_models.Proxy.type,
                db_models.Proxy.settings,
                db_models.excluded_inbounds_association.c.inbound_tag,
            ).join(
                db_models.Proxy, db_models.User.id == db_models.Proxy.user_id
            ).outerjoin(
                db_models.excluded_inbounds_association,
                db_models.Proxy.id == db_models.excluded_inbounds_association.c.proxy_id
            ).filter(
                db_models.User.status.in_([UserStatus.active, UserStatus.on_hold])
            )
            # Stream rows — materializing hundreds of thousands at once OOMs
            # the panel during core rebuild / health recovery.
            result_iter = query.yield_per(2000)

            # Aggregate excluded inbound tags per (proxy_type, user) in Python so
            # the query stays dialect-agnostic: lower(enum) and group_concat()
            # behave differently across SQLite / PostgreSQL / MySQL.
            grouped_data = defaultdict(list)
            _seen = {}
            user_speed: dict[int, tuple] = {}

            for row in result_iter:
                proxy_type = row.type.value if hasattr(row.type, "value") else str(row.type)
                proxy_type = proxy_type.lower()
                key = (proxy_type, row.id)
                entry = _seen.get(key)
                if entry is None:
                    entry = [row.id, row.username, row.settings, []]
                    _seen[key] = entry
                    grouped_data[proxy_type].append(entry)
                user_speed[row.id] = (row.speed_limit_up, row.speed_limit_down)
                if row.inbound_tag and row.inbound_tag not in entry[3]:
                    entry[3].append(row.inbound_tag)

            # Per-user Xray policy levels (stats only — speed is enforced via tier ports + tc).
            policy_levels = config.get("policy", {}).get("levels") or {}
            for uid, (up, down) in user_speed.items():
                if not up and not down:
                    continue
                level = str((uid % 9000) + 100)
                policy_levels[level] = {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                    "statsUserOnline": True,
                }
            if policy_levels:
                config.setdefault("policy", {})["levels"] = policy_levels

            for proxy_type, rows in grouped_data.items():

                inbounds = self.inbounds_by_protocol.get(proxy_type)
                if not inbounds:
                    continue

                for inbound in inbounds:
                    inbound_cfg = config.get_inbound(inbound['tag'])
                    if not inbound_cfg:
                        # inbounds_by_protocol drifted from the actual config
                        # (tag not present) — nothing to attach clients to.
                        continue
                    clients = inbound_cfg['settings']['clients']

                    for row in rows:
                        user_id, username, settings, excluded_inbound_tags = row

                        if excluded_inbound_tags and inbound['tag'] in excluded_inbound_tags:
                            continue

                        client = {
                            "email": f"{user_id}.{username}",
                            **settings
                        }
                        # Xray 26+ rejects flow on Trojan inbounds entirely.
                        if inbound['protocol'] == ProxyTypes.Trojan.value:
                            client.pop('flow', None)
                        elif inbound['protocol'] == ProxyTypes.VLESS.value:
                            client['flow'] = effective_vless_flow(client.get('flow'), inbound)
                        up, down = user_speed.get(user_id, (None, None))
                        if up or down:
                            client["level"] = (user_id % 9000) + 100

                        if inbound['protocol'] == ProxyTypes.Shadowsocks.value:
                            from xray_api.types.account import is_ss2022
                            raw_in = config.get_inbound(inbound['tag']) or {}
                            in_method = (
                                (raw_in.get('settings') or {}).get('method')
                                or inbound.get('ss_method')
                                or ''
                            )
                            user_method = settings.get('method') or ''
                            in_is_2022 = is_ss2022(in_method)
                            user_is_2022 = is_ss2022(user_method)
                            # Never mix legacy SS users into a 2022 inbound (or vice versa).
                            if in_is_2022 != user_is_2022:
                                continue
                            if in_is_2022:
                                client.pop('method', None)

                        # XTLS currently only supports transmission methods of TCP and mKCP
                        if client.get('flow') and (
                                inbound.get('network', 'tcp') not in ('tcp', 'raw', 'kcp')
                                or
                                (
                                    inbound.get('network', 'tcp') in ('tcp', 'raw', 'kcp')
                                    and
                                    inbound.get('tls') not in ('tls', 'reality')
                                )
                                or
                                inbound.get('header_type') == 'http'
                        ):
                            del client['flow']

                        clients.append(client)

                self._inject_xray_awg_peers(config, grouped_data)
                traffic_limits = self._apply_shadowsocks_speed_tiers(config, user_speed)
                if traffic_limits:
                    config["traffic_limits"] = traffic_limits

        if DEBUG:
            with open('generated_config-debug.json', 'w') as f:
                f.write(config.to_json(indent=4))

        return config
