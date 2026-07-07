"""Hysteria2 / TUIC / AnyTLS subscription link generators.

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
    insecure: bool = True,
    speed_limit_up: Optional[int] = None,
    speed_limit_down: Optional[int] = None,
) -> str:
    """Build a ``hysteria2://`` share link."""
    query = {}
    if insecure:
        query["insecure"] = "1"
    if sni:
        query["sni"] = sni
    if obfs_password:
        query["obfs"] = "salamander"
        query["obfs-password"] = obfs_password
    if speed_limit_up:
        query["up_mbps"] = str(int(speed_limit_up))
    if speed_limit_down:
        query["down_mbps"] = str(int(speed_limit_down))
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
    insecure: bool = True,
) -> str:
    """Build a ``tuic://`` share link."""
    # TUIC has no official URI spec; clients disagree on TLS skip flags (insecure vs
    # allow_insecure) and often expect udp_relay_mode + alpn for sing-box peers.
    query = {
        "congestion_control": congestion_control,
        "udp_relay_mode": "native",
        "alpn": "h3",
    }
    if insecure:
        query["insecure"] = "1"
        query["allow_insecure"] = "1"
    if sni:
        query["sni"] = sni
    q = f"?{parse.urlencode(query)}"
    frag = f"#{parse.quote(remark)}" if remark else ""
    auth = f"{parse.quote(uuid, safe='')}:{parse.quote(password, safe='')}"
    return f"tuic://{auth}@{host}:{port}{q}{frag}"


def anytls_link(
    *,
    password: str,
    host: str,
    port: int,
    sni: Optional[str] = None,
    remark: str = "",
    insecure: bool = True,
) -> str:
    """Build an ``anytls://`` share link (password in auth segment)."""
    query = {}
    if insecure:
        query["insecure"] = "1"
    if sni:
        query["sni"] = sni
    q = f"?{parse.urlencode(query)}" if query else ""
    frag = f"#{parse.quote(remark)}" if remark else ""
    auth = parse.quote(password, safe="")
    return f"anytls://{auth}@{host}:{port}{q}{frag}"


def singbox_link_insecure(cfg) -> bool:
    """Whether share links must skip TLS verify for this node's sing-box TLS."""
    from app.tls.inspect import cert_requires_insecure

    if cfg is None:
        return True
    return cert_requires_insecure(
        tls_trusted=getattr(cfg, "tls_trusted", False),
        sni=cfg.sni,
    )


def user_hysteria2_link(
    user_settings: dict,
    dbnode,
    remark: str = "",
    *,
    insecure: Optional[bool] = None,
    speed_limit_up: Optional[int] = None,
    speed_limit_down: Optional[int] = None,
) -> Optional[str]:
    cfg = dbnode.singbox
    if cfg is None or not cfg.hysteria2_enabled or not cfg.hysteria2_port:
        return None
    password = user_settings.get("password")
    if not password:
        return None
    host = node_host(dbnode)
    if insecure is None:
        insecure = singbox_link_insecure(cfg)
    from app.singbox.sync import hysteria2_port_for_user

    port = hysteria2_port_for_user(
        int(cfg.hysteria2_port),
        speed_limit_up,
        speed_limit_down,
    )
    from app.singbox.speed import speed_tier

    tier = speed_tier(speed_limit_up, speed_limit_down)
    return hysteria2_link(
        password=password,
        host=host,
        port=port,
        sni=cfg.sni or host,
        obfs_password=cfg.hysteria2_obfs_password,
        remark=remark,
        insecure=insecure,
        speed_limit_up=None if tier else speed_limit_up,
        speed_limit_down=None if tier else speed_limit_down,
    )


def user_tuic_link(
    user_settings: dict,
    dbnode,
    remark: str = "",
    *,
    insecure: Optional[bool] = None,
    speed_limit_up: Optional[int] = None,
    speed_limit_down: Optional[int] = None,
) -> Optional[str]:
    cfg = dbnode.singbox
    if cfg is None or not cfg.tuic_enabled or not cfg.tuic_port:
        return None
    uuid = user_settings.get("uuid")
    password = user_settings.get("password")
    if not uuid or not password:
        return None
    host = node_host(dbnode)
    if insecure is None:
        insecure = singbox_link_insecure(cfg)
    from app.singbox.sync import tuic_port_for_user

    port = tuic_port_for_user(int(cfg.tuic_port), speed_limit_up, speed_limit_down)
    return tuic_link(
        uuid=str(uuid),
        password=password,
        host=host,
        port=port,
        sni=cfg.sni or host,
        congestion_control=cfg.tuic_congestion_control or "bbr",
        remark=remark,
        insecure=insecure,
    )


def user_anytls_link(
    user_settings: dict,
    dbnode,
    remark: str = "",
    *,
    insecure: Optional[bool] = None,
    speed_limit_up: Optional[int] = None,
    speed_limit_down: Optional[int] = None,
) -> Optional[str]:
    cfg = dbnode.singbox
    if cfg is None or not cfg.anytls_enabled or not cfg.anytls_port:
        return None
    password = user_settings.get("password")
    if not password:
        return None
    host = node_host(dbnode)
    if insecure is None:
        insecure = singbox_link_insecure(cfg)
    from app.singbox.sync import anytls_port_for_user

    port = anytls_port_for_user(int(cfg.anytls_port), speed_limit_up, speed_limit_down)
    return anytls_link(
        password=password,
        host=host,
        port=port,
        sni=cfg.sni or host,
        remark=remark,
        insecure=insecure,
    )
