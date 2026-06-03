"""Phase 11.2 — node-side WireGuard manager (pure, root-free unit tests)."""
from node.wireguard import (
    WireGuardManager,
    WireGuardPeer,
    WireGuardSpec,
    parse_transfer,
    render_syncconf,
)


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Recorder:
    """Captures commands and returns scripted results keyed by a command token."""

    def __init__(self, results=None):
        self.calls = []
        self.inputs = []
        self.results = results or {}

    def __call__(self, cmd, input=None, check=True):
        self.calls.append(cmd)
        self.inputs.append(input)
        for token, result in self.results.items():
            if token in cmd:
                return result
        return _FakeResult(returncode=0)


# --------------------------------------------------------------------------- #
# transfer parsing — the heart of WireGuard accuracy
# --------------------------------------------------------------------------- #
def test_parse_transfer_tab_separated():
    out = "PUBKEYA\t1000\t2000\nPUBKEYB\t5\t7\n"
    parsed = parse_transfer(out)
    assert parsed["PUBKEYA"] == {"rx": 1000, "tx": 2000}
    assert parsed["PUBKEYB"] == {"rx": 5, "tx": 7}


def test_parse_transfer_ignores_blank_and_malformed():
    out = "\nPUBKEYA\t10\t20\nGARBAGE\nPUBKEYC\tx\ty\n"
    parsed = parse_transfer(out)
    assert parsed == {"PUBKEYA": {"rx": 10, "tx": 20}}


def test_parse_transfer_whitespace_separated_fallback():
    parsed = parse_transfer("PUBKEYA 100 200")
    assert parsed["PUBKEYA"] == {"rx": 100, "tx": 200}


# --------------------------------------------------------------------------- #
# syncconf rendering
# --------------------------------------------------------------------------- #
def test_render_syncconf_includes_interface_and_peers():
    spec = WireGuardSpec(
        interface="nxwg0",
        listen_port=51820,
        private_key="PRIV",
        address=["10.10.0.1/24"],
        peers=[
            WireGuardPeer(public_key="PUB1", allowed_ips=["10.10.0.2/32"]),
            WireGuardPeer(public_key="PUB2", allowed_ips=["10.10.0.3/32"], preshared_key="PSK"),
        ],
    )
    conf = render_syncconf(spec)
    assert "[Interface]" in conf
    assert "ListenPort = 51820" in conf
    assert "PrivateKey = PRIV" in conf
    assert conf.count("[Peer]") == 2
    assert "PublicKey = PUB1" in conf
    assert "AllowedIPs = 10.10.0.2/32" in conf
    assert "PresharedKey = PSK" in conf
    # Address/MTU are applied via `ip`, never in the stripped syncconf.
    assert "Address" not in conf


# --------------------------------------------------------------------------- #
# spec from_dict
# --------------------------------------------------------------------------- #
def test_spec_from_dict_normalizes_address_and_peers():
    spec = WireGuardSpec.from_dict({
        "interface": "nxwg0",
        "listen_port": "51820",
        "private_key": "PRIV",
        "address": "10.10.0.1/24",
        "mtu": "1420",
        "peers": [{"public_key": "PUB1", "allowed_ips": ["10.10.0.2/32"]}],
    })
    assert spec.address == ["10.10.0.1/24"]
    assert spec.listen_port == 51820
    assert spec.mtu == 1420
    assert spec.peers[0].public_key == "PUB1"


# --------------------------------------------------------------------------- #
# manager command sequencing with a fake runner (no root, no wg)
# --------------------------------------------------------------------------- #
def test_apply_creates_interface_when_missing_then_syncconf():
    rec = _Recorder(results={"show": _FakeResult(returncode=1)})  # interface missing
    mgr = WireGuardManager(run=rec)
    spec = WireGuardSpec(interface="nxwg0", listen_port=51820, private_key="PRIV",
                         address=["10.10.0.1/24"],
                         peers=[WireGuardPeer("PUB1", ["10.10.0.2/32"])])
    mgr.apply(spec)

    flat = [" ".join(c) for c in rec.calls]
    assert any("ip link add dev nxwg0 type wireguard" in c for c in flat)
    assert any("ip link set up dev nxwg0" in c for c in flat)
    assert any("wg syncconf nxwg0" in c for c in flat)
    # the rendered config was piped as stdin to syncconf
    assert any(inp and "PublicKey = PUB1" in inp for inp in rec.inputs)


def test_apply_skips_link_add_when_interface_exists():
    rec = _Recorder(results={"show": _FakeResult(returncode=0)})  # interface exists
    mgr = WireGuardManager(run=rec)
    spec = WireGuardSpec(interface="nxwg0", listen_port=51820, private_key="PRIV",
                         address=["10.10.0.1/24"])
    mgr.apply(spec)
    flat = [" ".join(c) for c in rec.calls]
    assert not any("link add" in c for c in flat)


def test_get_transfer_returns_empty_when_interface_down():
    rec = _Recorder(results={"transfer": _FakeResult(returncode=1)})
    mgr = WireGuardManager(run=rec)
    assert mgr.get_transfer("nxwg0") == {}


def test_get_transfer_parses_output():
    rec = _Recorder(results={"transfer": _FakeResult(returncode=0, stdout="PUB1\t11\t22\n")})
    mgr = WireGuardManager(run=rec)
    assert mgr.get_transfer("nxwg0") == {"PUB1": {"rx": 11, "tx": 22}}


def test_teardown_deletes_existing_interface():
    rec = _Recorder(results={"show": _FakeResult(returncode=0)})
    mgr = WireGuardManager(run=rec)
    mgr.teardown("nxwg0")
    flat = [" ".join(c) for c in rec.calls]
    assert any("ip link del dev nxwg0" in c for c in flat)
