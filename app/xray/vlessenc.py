"""Parse ``xray vlessenc`` output and build inbound decryption/encryption pairs."""

from __future__ import annotations

import re
import subprocess
from typing import TypedDict

from config import XRAY_EXECUTABLE_PATH

_KEY_GEN_TYPES: dict[str, tuple[str, str]] = {
    "none": ("x25519", "native"),
    "x25519": ("x25519", "native"),
    "x25519-xorpub": ("x25519", "xorpub"),
    "x25519-random": ("x25519", "random"),
    "mlkem768": ("mlkem768", "native"),
    "mlkem768-xorpub": ("mlkem768", "xorpub"),
    "mlkem768-random": ("mlkem768", "random"),
}


class VlessEncPair(TypedDict):
    decryption: str
    encryption: str
    keyGenType: str


class VlessEncAuth(TypedDict):
    id: str
    label: str
    decryption: str
    encryption: str


def _auth_id(label: str) -> str:
    upper = label.upper()
    if "ML-KEM" in upper:
        return "mlkem768"
    return "x25519"


def parse_vlessenc_auths(output: str) -> list[VlessEncAuth]:
    """Parse ``xray vlessenc`` stdout into auth option blocks."""
    auths: list[VlessEncAuth] = []
    current: dict[str, str] | None = None

    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Authentication:"):
            if current and current.get("decryption") and current.get("encryption"):
                auths.append(
                    VlessEncAuth(
                        id=current["id"],
                        label=current["label"],
                        decryption=current["decryption"],
                        encryption=current["encryption"],
                    )
                )
            label = line[len("Authentication:") :].strip()
            current = {"id": _auth_id(label), "label": label}
            continue

        m = re.match(r'^"(decryption|encryption)"\s*:\s*"(.+)"\s*,?\s*$', line)
        if m and current is not None:
            current[m.group(1)] = m.group(2)

    if current and current.get("decryption") and current.get("encryption"):
        auths.append(
            VlessEncAuth(
                id=current["id"],
                label=current["label"],
                decryption=current["decryption"],
                encryption=current["encryption"],
            )
        )

    return auths


def apply_enc_method(value: str, method: str) -> str:
    """Replace the 2nd dot-separated block (native/xorpub/random)."""
    parts = value.split(".")
    if len(parts) < 2:
        return value
    parts[1] = method
    return ".".join(parts)


def select_vlessenc_pair(auths: list[VlessEncAuth], key_gen_type: str) -> VlessEncPair:
    family, method = _KEY_GEN_TYPES.get(key_gen_type, _KEY_GEN_TYPES["x25519"])
    resolved_type = "x25519" if key_gen_type == "none" else key_gen_type

    match = next((a for a in auths if a["id"] == family), None)
    if not match:
        raise ValueError(f"No VLESS encryption auth found for {family}")

    return VlessEncPair(
        decryption=apply_enc_method(match["decryption"], method),
        encryption=apply_enc_method(match["encryption"], method),
        keyGenType=resolved_type if resolved_type != "none" else "x25519",
    )


def run_vlessenc(key_gen_type: str = "x25519") -> VlessEncPair:
    """Execute ``xray vlessenc`` and return the requested auth pair."""
    try:
        proc = subprocess.run(
            [XRAY_EXECUTABLE_PATH, "vlessenc"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"failed to run `{XRAY_EXECUTABLE_PATH} vlessenc`: {exc}") from exc

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        tail = output.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"xray vlessenc failed: {tail}")

    auths = parse_vlessenc_auths(output)
    if not auths:
        raise RuntimeError("xray vlessenc returned no auth options")

    return select_vlessenc_pair(auths, key_gen_type)
