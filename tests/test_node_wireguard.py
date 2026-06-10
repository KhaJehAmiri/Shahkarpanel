"""Phase 11.2 — node-side WireGuard manager (pure, root-free unit tests)."""
from node.wireguard import (
    WireGuardManager,
    WireGuardPeer,
    WireGuardSpec,
    ensure_egress_forwarding,
    parse_transfer,
    render_syncconf,
    subnets_from_specs,
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


def test_render_syncconf_omits_amnezia_when_disabled():
    spec = WireGuardSpec(
        interface="nxwg0",
        listen_port=51820,
        private_key="PRIV",
        address=["10.10.0.1/24"],
        amnezia={"Jc": 4, "Jmin": 50, "Jmax": 1000},
    )
    conf = render_syncconf(spec, include_amnezia=False)
    assert "Jc" not in conf
    assert render_syncconf(spec, include_amnezia=True).count("Jc = 4") == 1


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
    rec = _Recorder(results={
        "show": _FakeResult(returncode=1),  # interface missing
        "pgrep": _FakeResult(returncode=1),
    })
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
    rec = _Recorder(results={
        "show": _FakeResult(returncode=0),  # interface exists
        "pgrep": _FakeResult(returncode=1),  # plain kernel wg, not userspace AWG
    })
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


def test_subnets_from_specs_dedupes_networks():
    specs = [
        WireGuardSpec("wg0", 51820, "PRIV", ["10.10.0.1/24"]),
        WireGuardSpec("wg1", 51821, "PRIV2", ["10.11.0.1/24"]),
    ]
    assert subnets_from_specs(specs) == ["10.10.0.0/24", "10.11.0.0/24"]


def test_ensure_egress_forwarding_adds_nat_and_forward_rules(monkeypatch):
    rec = _Recorder(
        results={
            "route": _FakeResult(
                returncode=0,
                stdout="8.8.8.8 via 1.2.3.4 dev eth0 src 1.2.3.5 uid 0\n",
            ),
            "-C": _FakeResult(returncode=1),
            "-A": _FakeResult(returncode=0),
        }
    )
    monkeypatch.setattr("node.wireguard.shutil.which", lambda _: "/sbin/iptables")
    specs = [
        WireGuardSpec("wg0", 51820, "PRIV", ["10.10.0.1/24"]),
        WireGuardSpec("wg1", 51821, "PRIV2", ["10.11.0.1/24"]),
    ]
    ensure_egress_forwarding(specs, run=rec)
    flat = [" ".join(c) for c in rec.calls]
    assert any("-t nat -C POSTROUTING -s 10.10.0.0/24 -o eth0 -j MASQUERADE" in c for c in flat)
    assert any("-t nat -A POSTROUTING -s 10.11.0.0/24 -o eth0 -j MASQUERADE" in c for c in flat)
    assert any("FORWARD -i wg0 -j ACCEPT" in c for c in flat)
    assert any("FORWARD -o wg1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" in c for c in flat)
