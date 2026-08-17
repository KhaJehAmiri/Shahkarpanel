"""Normalize Xray inbounds before saving / restarting the core."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from xray_api.types.account import ShadowsocksMethods, is_ss2022

from app.models.proxy import _is_valid_ss2022_key


SHAHKAR_INBOUND_KIND = "shahkarPanelKind"

# Panel-only inbound flag stored in XRAY_JSON; stripped before Xray run/test.
SHAHKAR_INBOUND_ENABLE_KEY = "enable"

# Xray destOverride accepts only these protocols (bittorrent is routing-only).
SNIFF_DEST_OVERRIDE_ALLOWED = frozenset({"http", "tls", "quic", "fakedns"})
SNIFF_DEST_OVERRIDE_DEFAULT = ["http", "tls", "quic"]

DEFAULT_REALITY_TARGET = "www.cloudflare.com:443"


def inbound_is_enabled(inbound: Any) -> bool:
    """Return False only when the panel explicitly disabled the inbound."""
    if not isinstance(inbound, dict):
        return True
    val = inbound.get(SHAHKAR_INBOUND_ENABLE_KEY, inbound.get("enabled", True))
    if val is False or val == 0:
        return False
    if isinstance(val, str) and val.strip().lower() in ("false", "0", "off", "no"):
        return False
    return True


def strip_panel_inbound_fields(inbound: Dict[str, Any]) -> Dict[str, Any]:
    """Copy an inbound without panel-only keys that Xray must not see."""
    out = dict(inbound)
    out.pop(SHAHKAR_INBOUND_ENABLE_KEY, None)
    out.pop("enabled", None)
    return out


def runtime_core_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Config safe for ``xray run``: drop disabled inbounds and panel-only keys.

    Disabled inbounds remain in the stored ``XRAY_JSON`` so the UI can re-enable
    them; they are omitted from the live core / node restart payload.
    """
    result = deepcopy(config)
    kept: List[Dict[str, Any]] = []
    for ib in result.get("inbounds") or []:
        if not isinstance(ib, dict):
            continue
        if not inbound_is_enabled(ib):
            continue
        kept.append(strip_panel_inbound_fields(ib))
    result["inbounds"] = kept
    return result


def ensure_inbound_enable_flags(data: Dict[str, Any]) -> Dict[str, Any]:
    """Default missing ``enable`` to True on every inbound (idempotent)."""
    for ib in data.get("inbounds") or []:
        if isinstance(ib, dict) and SHAHKAR_INBOUND_ENABLE_KEY not in ib:
            ib[SHAHKAR_INBOUND_ENABLE_KEY] = True
    return data


def _reality_target_from_settings(rs: Dict[str, Any]) -> str:
    for key in ("target", "dest"):
        if key not in rs:
            continue
        val = str(rs.get(key) or "").strip()
        if val:
            return val
    names = rs.get("serverNames") or rs.get("serverName")
    if isinstance(names, list):
        for name in names:
            sni = str(name or "").strip()
            if sni:
                return f"{sni}:443"
    elif isinstance(names, str) and names.strip():
        return f"{names.strip()}:443"
    return DEFAULT_REALITY_TARGET


def _normalize_reality_settings(rs: Dict[str, Any]) -> bool:
    if not isinstance(rs, dict):
        return False

    changed = False
    if "target" in rs and not str(rs.get("target") or "").strip():
        rs.pop("target", None)
        changed = True

    target = _reality_target_from_settings(rs)
    if str(rs.get("target") or "").strip() != target:
        rs["target"] = target
        changed = True

    if "dest" in rs:
        rs.pop("dest", None)
        changed = True

    return changed


def _xhttp_host_empty(xh: Dict[str, Any]) -> bool:
    host = xh.get("host")
    if host in (None, "", [], {}):
        return True
    if isinstance(host, list) and not any(str(x).strip() for x in host):
        return True
    if isinstance(host, str) and not host.strip():
        return True
    return False


def _sni_hint_from_stream(stream: Dict[str, Any]) -> str | None:
    rs = stream.get("realitySettings")
    if isinstance(rs, dict):
        names = rs.get("serverNames") or rs.get("serverName")
        if isinstance(names, list):
            for name in names:
                sni = str(name or "").strip()
                if sni:
                    return sni
        sni = str(names or "").strip()
        if sni:
            return sni
    tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        sni = str(tls.get("serverName") or "").strip()
        if sni:
            return sni
    return None


def _normalize_xhttp_client_compat(stream: Dict[str, Any]) -> bool:
    """``packet-up`` with an empty host only works if the client also uses
    ``packet-up``. Stock clients send ``mode=auto`` and fail. Server ``auto``
    accepts every XHTTP mode, so it is the compatible default when host is
    missing. Also copy SNI into host so the HTTP request has a Host header.
    """
    net = str(stream.get("network") or "").lower()
    if net not in ("xhttp", "splithttp"):
        return False
    key = "xhttpSettings" if isinstance(stream.get("xhttpSettings"), dict) else (
        "splithttpSettings" if isinstance(stream.get("splithttpSettings"), dict) else None
    )
    if key is None:
        return False
    xh = stream[key]
    changed = False
    mode = str(xh.get("mode") or "auto").strip().lower()
    if mode == "packet-up" and _xhttp_host_empty(xh):
        xh["mode"] = "auto"
        changed = True
    if _xhttp_host_empty(xh):
        hint = _sni_hint_from_stream(stream)
        if hint:
            xh["host"] = hint
            changed = True
    return changed


def _normalize_inbound_stream(stream: Dict[str, Any]) -> bool:
    changed = False
    if migrate_legacy_quic_stream_settings(stream):
        changed = True
    if _normalize_xhttp_client_compat(stream):
        changed = True
    tls = stream.get("tlsSettings")
    if isinstance(tls, dict) and _normalize_tls_ech_fields(tls):
        changed = True
    if str(stream.get("security") or "").lower() == "reality":
        rs = stream.get("realitySettings")
        if not isinstance(rs, dict):
            rs = {}
            stream["realitySettings"] = rs
            changed = True
        if _normalize_reality_settings(rs):
            changed = True
    return changed


def normalize_ss2022_psk(value: str, method: str | ShadowsocksMethods) -> str | None:
    """Return a standard-base64 SS-2022 PSK, fixing legacy URL-safe keys from the UI."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        cipher = method if isinstance(method, ShadowsocksMethods) else ShadowsocksMethods(method)
    except ValueError:
        return None

    if _is_valid_ss2022_key(raw, cipher):
        return raw

    # Dashboard used to emit URL-safe base64 (RFC 4648 §5) for generated passwords.
    candidate = raw.replace("-", "+").replace("_", "/")
    pad = (-len(candidate) % 4)
    if pad:
        candidate += "=" * pad
    if _is_valid_ss2022_key(candidate, cipher):
        return candidate
    return None


def _normalize_shadowsocks_settings(settings: Dict[str, Any]) -> bool:
    method = str(settings.get("method") or "")
    if not is_ss2022(method):
        return False

    key = str(settings.get("password") or settings.get("key") or "").strip()
    normalized = normalize_ss2022_psk(key, method)
    if not normalized:
        return False

    changed = normalized != key or "key" in settings
    settings["password"] = normalized
    settings.pop("key", None)
    return changed


def _normalize_sniffing(sniff: Dict[str, Any]) -> bool:
    if not isinstance(sniff, dict):
        return False

    dest = sniff.get("destOverride")
    if not isinstance(dest, list):
        return False

    seen: set[str] = set()
    filtered: List[str] = []
    for item in dest:
        proto = str(item).strip().lower()
        if proto not in SNIFF_DEST_OVERRIDE_ALLOWED or proto in seen:
            continue
        seen.add(proto)
        filtered.append(proto)

    if filtered == dest:
        return False

    if filtered:
        sniff["destOverride"] = filtered
    else:
        sniff.pop("destOverride", None)
        if sniff.get("enabled") is not False:
            sniff["destOverride"] = list(SNIFF_DEST_OVERRIDE_DEFAULT)
    return True


def normalize_vless_inbound_settings(settings: dict) -> bool:
    """Ensure VLESS inbounds always have ``decryption`` (Xray requires it)."""
    if not isinstance(settings, dict):
        return False
    changed = False
    dec = str(settings.get("decryption") or "").strip()
    enc_raw = settings.get("encryption")
    enc = str(enc_raw).strip() if enc_raw is not None else ""

    if not dec:
        settings["decryption"] = "none"
        changed = True

    if enc.lower() == "none":
        if settings.pop("encryption", None) is not None:
            changed = True

    return changed


def _ech_to_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, list):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return parts[0] if parts else None
    s = str(value).strip()
    return s or None


def migrate_legacy_quic_stream_settings(stream: Dict[str, Any]) -> bool:
    """Upgrade legacy ``network: quic`` to XHTTP stream-one H3 (Xray 26+)."""
    if str(stream.get("network") or "").lower() != "quic":
        return False

    quic = dict(stream.get("quicSettings") or {})
    key = str(quic.get("key") or "").strip()
    if key and not key.startswith("/"):
        path = f"/{key}"
    else:
        path = key or "/"

    stream.pop("quicSettings", None)
    stream["network"] = "xhttp"

    xh = dict(stream.get("xhttpSettings") or {})
    if not str(xh.get("path") or "").strip():
        xh["path"] = path
    xh["mode"] = "stream-one"
    stream["xhttpSettings"] = xh

    sec = str(stream.get("security") or "").lower()
    if sec in ("", "none"):
        stream["security"] = "tls"

    tls = stream.get("tlsSettings")
    if not isinstance(tls, dict):
        tls = {}
        stream["tlsSettings"] = tls

    alpn = tls.get("alpn")
    if not isinstance(alpn, list):
        alpn = []
    if "h3" not in alpn:
        tls["alpn"] = ["h3"] + [a for a in alpn if a != "h3"]

    return True


def _normalize_tls_ech_fields(tls: Dict[str, Any]) -> bool:
    changed = False
    for key in ("echServerKeys", "echConfigList"):
        if key not in tls:
            continue
        normalized = _ech_to_string(tls.get(key))
        if normalized is None:
            if tls.pop(key, None) is not None:
                changed = True
        elif tls.get(key) != normalized:
            tls[key] = normalized
            changed = True
    return changed


def normalize_core_config_payload(payload: dict) -> dict:
    """Normalize Xray JSON before save/restart.

    - Ensures ``inbounds`` is always a list (may be empty).
    - Restores minimal ``outbounds`` / ``routing`` when missing or cleared.
    - Converts wireguard/amneziawg inbounds to valid Xray wireguard JSON.
    """
    data = deepcopy(payload)

    if not isinstance(data.get("inbounds"), list):
        data["inbounds"] = []

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        data["outbounds"] = [
            {"protocol": "freedom", "tag": "DIRECT"},
            {"protocol": "blackhole", "tag": "BLOCK"},
        ]

    routing = data.get("routing")
    if not isinstance(routing, dict):
        data["routing"] = {"domainStrategy": "IPIfNonMatch", "rules": []}
    elif not isinstance(routing.get("rules"), list):
        routing["rules"] = []

    inbounds: List[Dict[str, Any]] = list(data.get("inbounds") or [])
    changed = False

    for inbound in inbounds:
        stream = inbound.get("streamSettings")
        if isinstance(stream, dict) and _normalize_inbound_stream(stream):
            changed = True

        sniff = inbound.get("sniffing")
        if isinstance(sniff, dict) and _normalize_sniffing(sniff):
            changed = True

        proto = str(inbound.get("protocol") or "").lower()
        if proto == "shadowsocks":
            settings = inbound.get("settings")
            if isinstance(settings, dict) and _normalize_shadowsocks_settings(settings):
                changed = True

        if proto == "vless":
            settings = inbound.get("settings")
            if isinstance(settings, dict) and normalize_vless_inbound_settings(settings):
                changed = True

        if proto not in ("wireguard", "amneziawg"):
            continue

        settings = dict(inbound.get("settings") or {})
        is_amnezia = proto == "amneziawg" or settings.get(SHAHKAR_INBOUND_KIND) == "amneziawg"

        inbound["protocol"] = "wireguard"
        inbound.pop("streamSettings", None)
        inbound.pop("sniffing", None)
        settings.pop("clients", None)

        if is_amnezia:
            settings[SHAHKAR_INBOUND_KIND] = "amneziawg"

        secret = str(settings.get("secretKey") or "").strip()
        if not secret:
            from app.wireguard import generate_keypair

            secret, _pub = generate_keypair()
            settings["secretKey"] = secret
            changed = True

        try:
            mtu = int(settings.get("mtu") or 1420)
        except (TypeError, ValueError):
            mtu = 1420
        settings["mtu"] = mtu

        peers = settings.get("peers")
        if not isinstance(peers, list):
            settings["peers"] = []

        inbound["settings"] = settings
        changed = True

    data["inbounds"] = inbounds
    ensure_inbound_enable_flags(data)

    from app.xray.warp_routing import apply_warp_safe_routing

    return apply_warp_safe_routing(data)
