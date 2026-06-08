"""Hysteria2 / TUIC subscription link generators.

These protocols are served by the node's sing-box engine (not Xray inbounds), so
they cannot ride the standard ``share.py`` inbound loop. Like WireGuard they use
dedicated subscription endpoints tied to the same token and central quota.
"""
from typing import Optional
from urllib import parse


def node_host(dbnode) -> str:
    """Client-facing host for a sing-box node."""
    cfg = dbnode.singbox
    if cfg and cfg.sni:
        return cfg.sni
    return dbnode.address


def hysteria2_link(
    *,
    password: str,
    host: str,
    port: int,
    sni: Optional[str] = None,
    obfs_password: Optional[str] = None,
    remark: str = "",
) -> str:
    """Build a ``hysteria2://`` share link."""
    query = {}
    if sni:
        query["sni"] = sni
    if obfs_password:
        query["obfs-password"] = obfs_password
    q = f"?{parse.urlencode(query)}" if query else ""
    frag = f"#{parse.quote(remark)}" if remark else ""
    auth = parse.quote(password, safe="")
    return f"hysteria2://{auth}@{host}:{port}{q}{frag}"


def tuic_link(
    *,
    uuid: str,
    password: str,
    host: str,
    port: int,
    sni: Optional[str] = None,
    congestion_control: str = "bbr",
    remark: str = "",
) -> str:
    """Build a ``tuic://`` share link."""
    query = {"congestion_control": congestion_control}
    if sni:
        query["sni"] = sni
    q = f"?{parse.urlencode(query)}"
    frag = f"#{parse.quote(remark)}" if remark else ""
    auth = f"{parse.quote(uuid, safe='')}:{parse.quote(password, safe='')}"
    return f"tuic://{auth}@{host}:{port}{q}{frag}"


def user_hysteria2_link(user_settings: dict, dbnode, remark: str = "") -> Optional[str]:
    cfg = dbnode.singbox
    if cfg is None or not cfg.hysteria2_enabled or not cfg.hysteria2_port:
        return None
    password = user_settings.get("password")
    if not password:
        return None
    host = node_host(dbnode)
    return hysteria2_link(
        password=password,
        host=host,
        port=int(cfg.hysteria2_port),
        sni=cfg.sni or host,
        obfs_password=cfg.hysteria2_obfs_password,
        remark=remark,
    )


def user_tuic_link(user_settings: dict, dbnode, remark: str = "") -> Optional[str]:
    cfg = dbnode.singbox
    if cfg is None or not cfg.tuic_enabled or not cfg.tuic_port:
        return None
    uuid = user_settings.get("uuid")
    password = user_settings.get("password")
    if not uuid or not password:
        return None
    host = node_host(dbnode)
    return tuic_link(
        uuid=str(uuid),
        password=password,
        host=host,
        port=int(cfg.tuic_port),
        sni=cfg.sni or host,
        congestion_control=cfg.tuic_congestion_control or "bbr",
        remark=remark,
    )
