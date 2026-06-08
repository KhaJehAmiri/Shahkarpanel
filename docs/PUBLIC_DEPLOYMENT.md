# NexusPanel for public operators (Marzban-style)

NexusPanel is built to serve **two audiences from one backend**, with no code
forks:

| Layer | Who uses it | How |
| --- | --- | --- |
| **1. Standard subscription** | Anyone who installs the panel and resells access to customers | Off-the-shelf protocol apps (v2rayNG, Hiddify, sing-box, Clash Meta, WireGuard, AmneziaWG) consuming the panel's subscription URL / `.conf` |
| **2. Smart Client API** | Optional branded/white-label apps | `/api/v2/client/*`, gated behind the `client_api` feature flag (off by default) |

The golden rule: **everything the Client API serves is also expressible as a
standard subscription.** A public operator never needs a custom app, and the
smart layer (profiles, negotiation, dedicated IPs) is purely additive.

## Layer 1 — selling configs with standard apps

Every user gets a stable subscription URL (`subscription_url` on the user
object, shown on the user page and the public `/subscribe` page). Point your
customers at it and they connect with the free app for their protocol.

### Which app for which protocol

| Protocol(s) | Recommended client apps |
| --- | --- |
| VLESS / VMess / Trojan / Reality / Shadowsocks | v2rayNG, Hiddify, NekoBox / sing-box, Streisand (iOS), Clash Meta |
| WireGuard | Official WireGuard app (Android/iOS/Win/macOS/Linux), WireSock (Windows) |
| **AmneziaWG** (obfuscated WireGuard) | **Amnezia VPN / AmneziaWG app** — import the same `.conf`; the panel emits `Jc/Jmin/Jmax/S1/S2/H1–H4` under `[Interface]` automatically |

The `/subscribe` page renders these app tiles per platform with download links
and one-tap import, including a dedicated **WireGuard** tab that now lists the
**AmneziaWG** app whenever the user has a WireGuard/AmneziaWG proxy.

### WireGuard & AmneziaWG endpoints

- `GET /sub/<token>/wireguard` → a ready-to-import `wg-quick` `.conf`.
- If the chosen node has AmneziaWG parameters configured (System → WireGuard →
  *AmneziaWG obfuscation*), the same `.conf` carries the obfuscation fields, so
  it works in the AmneziaWG app and stays compatible with plain WireGuard when
  left unconfigured.

## Layer 2 — the smart client-app layer (optional)

Leave the `client_api` flag **off** if you only resell standard configs. When a
branded app is in play, enable it under **System → Feature flags** to unlock:

- `client_profile` per user (Regular / Gamer / Trader) — tunes protocol order
  and node selection.
- Protocol negotiation, client probes, telemetry, push device tokens.
- **Dedicated IPs** (Connectivity → Dedicated IPs) — a static-IP pool you pin to
  Trader users.

Because Layer 2 reuses Layer-1 configs under the hood, an operator who later
ships their own white-label app can build on the same API without any backend
changes.

See [`CLIENT_API.md`](./CLIENT_API.md) for the full Client API reference.
