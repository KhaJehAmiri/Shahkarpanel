"""Structured Xray outbound descriptors for the SigmaGuard client API."""
from typing import List, Union

from xray_api.types.account import is_ss2022


class StructuredXrayExport:
    """Collects structured connection entries (parallel to ``V2rayShareLink``)."""

    def __init__(self):
        self.entries: List[dict] = []

    def add(self, remark: str, address: str, inbound: dict, settings: dict):
        protocol = inbound.get("protocol", "")
        net = inbound.get("network", "tcp")
        tls = inbound.get("tls", "none")
        entry = {
            "protocol": protocol,
            "remark": remark,
            "address": address,
            "port": inbound.get("port"),
            "network": net,
            "tls": tls,
            "sni": inbound.get("sni") or "",
            "host": inbound.get("host") or "",
            "path": inbound.get("path") or "",
            "fingerprint": inbound.get("fp") or "",
            "alpn": inbound.get("alpn") or "",
            "allow_insecure": bool(inbound.get("ais")),
        }
        if protocol == "vless":
            entry["uuid"] = str(settings.get("id", ""))
            entry["flow"] = settings.get("flow") or ""
            if tls == "reality":
                entry["reality"] = {
                    "public_key": inbound.get("pbk") or "",
                    "short_id": inbound.get("sid") or "",
                    "spider_x": inbound.get("spx") or "",
                }
        elif protocol == "shadowsocks":
            method = settings.get("method", "")
            entry["method"] = method
            entry["password"] = settings.get("password", "")
            entry["is_ss2022"] = is_ss2022(method)
        elif protocol == "vmess":
            entry["uuid"] = str(settings.get("id", ""))
        elif protocol == "trojan":
            entry["password"] = settings.get("password", "")

        if net == "ws":
            entry["ws"] = {"path": entry["path"], "host": entry["host"]}
        elif net == "grpc":
            entry["grpc"] = {
                "service_name": entry["path"],
                "authority": entry["host"],
                "multi_mode": inbound.get("multiMode", False),
            }

        entry["kind"] = _classify_entry(entry)
        self.entries.append(entry)

    def render(self, reverse: bool = False) -> List[dict]:
        if reverse:
            return list(reversed(self.entries))
        return self.entries


def _classify_entry(entry: dict) -> str:
    protocol = entry.get("protocol")
    if protocol == "vless" and entry.get("tls") == "reality":
        return "vless-reality"
    if protocol == "vless" and entry.get("network") in ("ws", "http"):
        return "cdn"
    if protocol == "shadowsocks" and entry.get("is_ss2022"):
        return "shadowsocks-2022"
    if protocol == "shadowsocks":
        return "shadowsocks"
    return protocol or "unknown"


def build_structured_xray(user) -> List[dict]:
    """Return structured Xray outbounds for a ``UserResponse``-like object."""
    from app.subscription.share import process_inbounds_and_tags, setup_format_variables

    kwargs = {
        "proxies": user.proxies,
        "inbounds": user.inbounds,
        "extra_data": user.model_dump() if hasattr(user, "model_dump") else user.__dict__,
    }
    conf = StructuredXrayExport()
    format_variables = setup_format_variables(kwargs["extra_data"])
    return process_inbounds_and_tags(
        kwargs["inbounds"],
        kwargs["proxies"],
        format_variables,
        conf=conf,
        reverse=False,
    )


def entries_for_protocol(entries: List[dict], protocol: str) -> List[dict]:
    if protocol == "cdn":
        return [e for e in entries if e.get("kind") == "cdn"]
    if protocol == "vless-reality":
        return [e for e in entries if e.get("kind") == "vless-reality"]
    if protocol == "shadowsocks-2022":
        return [e for e in entries if e.get("kind") == "shadowsocks-2022"]
    return [e for e in entries if e.get("kind") == protocol]
