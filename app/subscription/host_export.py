"""3x-ui compatible host → subscription export helpers."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID


def conf_export_format(conf: Any) -> str:
    from app.subscription.clash import ClashConfiguration, ClashMetaConfiguration
    from app.subscription.outline import OutlineConfiguration
    from app.subscription.singbox import SingBoxConfiguration
    from app.subscription.v2ray import V2rayJsonConfig, V2rayShareLink

    if isinstance(conf, V2rayShareLink):
        return "raw"
    if isinstance(conf, V2rayJsonConfig):
        return "json"
    if isinstance(conf, (ClashMetaConfiguration, ClashConfiguration)):
        return "clash"
    if isinstance(conf, SingBoxConfiguration):
        return "singbox"
    if isinstance(conf, OutlineConfiguration):
        return "outline"
    from app.subscription.surge import SurgeConfiguration

    if isinstance(conf, SurgeConfiguration):
        return "surge"
    from app.subscription.loon import LoonConfiguration

    if isinstance(conf, LoonConfiguration):
        return "loon"
    from app.subscription.quantumult import QuantumultConfiguration

    if isinstance(conf, QuantumultConfiguration):
        return "quantumult"
    return "raw"


def _parse_csv_or_json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def host_excluded(host: dict[str, Any], export_format: str) -> bool:
    excluded = _parse_csv_or_json_list(host.get("exclude_from_sub_types"))
    if not excluded:
        return False
    fmt = export_format.lower()
    if fmt == "singbox":
        return "json" in excluded or "singbox" in excluded
    return fmt in excluded


def apply_vless_route(client_id: str, route: str | None) -> str:
    """Bake route port into VLESS UUID bytes 6-7 (3x-ui / Xray routing)."""
    text = str(route or "").strip()
    if not text:
        return client_id
    try:
        port = int(text)
    except ValueError:
        return client_id
    if port < 0 or port > 65535:
        return client_id
    try:
        uid = UUID(str(client_id))
    except ValueError:
        return client_id
    b = bytearray(uid.bytes)
    b[6] = (port >> 8) & 0xFF
    b[7] = port & 0xFF
    return str(UUID(bytes=bytes(b)))


def host_security_value(host: dict[str, Any]) -> str | None:
    """Normalized host security: inbound_default/same/none/tls/reality."""
    raw = host.get("tls")
    if raw is None:
        raw = host.get("security")
    text = str(raw or "inbound_default").strip().lower()
    if text in ("inbound_default", "same", ""):
        return None
    return text


def client_tls_from_host(
    host: dict[str, Any],
    *,
    inbound_tls: str,
    fronted: bool,
) -> str | None:
    """Map host security to client TLS mode (3x-ui forceTls)."""
    sec = host_security_value(host)
    if sec == "none":
        return "none"
    if sec == "tls":
        return "tls"
    if fronted and inbound_tls == "none":
        return "tls"
    if fronted:
        return inbound_tls if inbound_tls != "none" else "tls"
    return None


def resolve_host_sni(
    host: dict[str, Any],
    *,
    address: str,
    host_sni_override: str,
    resolved_sni: str,
) -> str:
    if host.get("keep_sni_blank"):
        return ""
    if host.get("override_sni_from_address"):
        domain = str(address or "").split(":", 1)[0].strip()
        if domain:
            return domain
    if host_sni_override:
        return host_sni_override
    return resolved_sni


def _parse_pin_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip().lower() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip().lower() for part in text.split(",") if part.strip()]


def host_tls_extras(host: dict[str, Any], *, fronted: bool) -> dict[str, Any]:
    """Per-host TLS trust overrides (3x-ui externalProxy fields)."""
    out: dict[str, Any] = {}
    ech = str(host.get("ech_config_list") or "").strip()
    if ech and not fronted:
        out["ech_config_list"] = ech
    pins = _parse_pin_list(host.get("pinned_peer_cert_sha256"))
    if pins and not fronted:
        out["cert_pin_sha256"] = pins[0]
    vcn = str(host.get("verify_peer_cert_by_name") or "").strip()
    if vcn:
        out["verify_peer_cert_by_name"] = vcn
    return out


def parse_json_object(text: Any) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def marshal_final_mask(final_mask: dict[str, Any] | None) -> str:
    if not final_mask:
        return ""
    try:
        blob = json.dumps(final_mask, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return ""
    return blob if blob and blob != "{}" else ""


def merge_stream_host_overrides(
    stream: dict[str, Any],
    host: dict[str, Any],
) -> dict[str, Any]:
    """Apply per-host sockopt / finalmask to JSON subscription streamSettings."""
    out = dict(stream or {})
    sockopt = parse_json_object(host.get("sockopt_params"))
    if sockopt:
        out["sockopt"] = sockopt
    final_mask = parse_json_object(host.get("final_mask"))
    if final_mask:
        existing = out.get("finalmask")
        if isinstance(existing, dict):
            merged = {**existing, **final_mask}
            out["finalmask"] = merged
        else:
            out["finalmask"] = final_mask
    return out


def parse_mux_params(host: dict[str, Any]) -> dict[str, Any] | None:
    return parse_json_object(host.get("mux_params"))


def parse_external_proxy_list(value: Any) -> list[dict[str, Any]]:
    """Parse ``external_proxy`` JSON array (3x-ui ``externalProxy`` entries)."""
    if not value:
        return []
    if isinstance(value, list):
        items = value
    else:
        raw = str(value).strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        items = parsed
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dest = str(item.get("dest") or item.get("address") or "").strip()
        if not dest:
            continue
        port_raw = item.get("port")
        try:
            port = int(port_raw) if port_raw not in (None, "") else None
        except (TypeError, ValueError):
            port = None
        force_tls = str(item.get("forceTls") or item.get("force_tls") or "same").strip().lower()
        alpn_raw = item.get("alpn")
        if isinstance(alpn_raw, list):
            alpn = ",".join(str(x).strip() for x in alpn_raw if str(x).strip())
        else:
            alpn = str(alpn_raw or "").strip()
        out.append(
            {
                "dest": dest,
                "port": port,
                "force_tls": force_tls if force_tls in ("same", "tls", "none") else "same",
                "sni": str(item.get("sni") or "").strip(),
                "fingerprint": str(item.get("fingerprint") or item.get("fp") or "").strip(),
                "alpn": alpn,
                "remark_suffix": str(item.get("remark") or "").strip(),
                "allow_insecure": bool(item.get("allowInsecure") or item.get("allow_insecure")),
                "pinned_peer_cert_sha256": item.get("pinnedPeerCertSha256")
                or item.get("pinned_peer_cert_sha256"),
                "verify_peer_cert_by_name": str(
                    item.get("verifyPeerCertByName") or item.get("verify_peer_cert_by_name") or ""
                ).strip(),
                "ech_config_list": str(
                    item.get("echConfigList") or item.get("ech_config_list") or ""
                ).strip(),
                "host_header": str(item.get("hostHeader") or item.get("host") or "").strip(),
                "path": str(item.get("path") or "").strip(),
                "vless_route": str(item.get("vlessRoute") or item.get("vless_route") or "").strip(),
            }
        )
    return out


def expand_host_export_variants(host: dict[str, Any]) -> list[dict[str, Any] | None]:
    """Return export overlays: ``None`` for the primary host row, then one per external hop."""
    extras = parse_external_proxy_list(host.get("external_proxy"))
    if not extras:
        return [None]
    return [None, *extras]


def apply_external_hop_to_host(
    host: dict[str, Any],
    hop: dict[str, Any],
) -> dict[str, Any]:
    """Merge an externalProxy hop onto a host dict for subscription export."""
    merged = dict(host)
    merged["address"] = [hop["dest"]]
    if hop.get("port") is not None:
        merged["port"] = hop["port"]
    if hop.get("force_tls") == "tls":
        merged["tls"] = "tls"
    elif hop.get("force_tls") == "none":
        merged["tls"] = "none"
    if hop.get("sni"):
        merged["sni"] = [hop["sni"]]
    if hop.get("host_header"):
        merged["host"] = [hop["host_header"]]
    if hop.get("path"):
        merged["path"] = hop["path"]
    if hop.get("fingerprint"):
        merged["fingerprint"] = hop["fingerprint"]
    if hop.get("alpn"):
        merged["alpn"] = hop["alpn"]
    if hop.get("allow_insecure"):
        merged["allowinsecure"] = True
    if hop.get("pinned_peer_cert_sha256"):
        pins = hop["pinned_peer_cert_sha256"]
        if isinstance(pins, list):
            merged["pinned_peer_cert_sha256"] = ",".join(str(x) for x in pins if str(x).strip())
        else:
            merged["pinned_peer_cert_sha256"] = str(pins)
    if hop.get("verify_peer_cert_by_name"):
        merged["verify_peer_cert_by_name"] = hop["verify_peer_cert_by_name"]
    if hop.get("ech_config_list"):
        merged["ech_config_list"] = hop["ech_config_list"]
    if hop.get("vless_route"):
        merged["vless_route"] = hop["vless_route"]
    suffix = hop.get("remark_suffix") or ""
    if suffix:
        base = str(merged.get("remark") or "")
        merged["remark"] = f"{base} {suffix}".strip() if base else suffix
    return merged

