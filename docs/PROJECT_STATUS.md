# NexusPanel — Project Status (handoff)

> **Last updated:** 2026-06-10  
> **Version:** 0.10.0  
> **مرجع مرکزی:** [`docs/CENTRAL-HANDOFF.md`](./CENTRAL-HANDOFF.md) · کانواس: `nexuspanel-central.canvas.tsx`

> ⚠️ کانواس‌های قدیمی (`nexuspanel-master-status`, `full-audit`, …) منسوخ و به **central** ادغام شدند.

## What is this project?

**NexusPanel** is a VPN/proxy control plane (AGPL-3.0, fork/evolution of Marzban-style panels) that manages:

- Users, quotas, subscriptions, resellers, billing (feature-flagged)
- Remote **nodes** (Docker agent) running Xray, native WireGuard, and sing-box (Hysteria2/TUIC)
- Optional **SigmaGuard** branded app via `/api/v2/client/*` (Flutter + Rust — not started yet)

**Two product layers:**

1. **Public subscription** — `/sub/{token}/` for v2rayNG, Hiddify, Nekobox, sing-box, WireGuard, H2, TUIC
2. **SigmaGuard app** — Client API on panel is ready; Flutter+Rust app is **next**

## Live infrastructure (this deployment)

| Item | Value |
|------|-------|
| Panel | `http://YOUR_PANEL_IP:8000` |
| Dashboard | `/dashboard/` |
| Subscribe | `/subscribe/?token=…` |
| Test node | `wireguard1` · id=**1** · `YOUR_WG_NODE_IP` |
| Test user | `alireza` · id=**5** |
| Repo path | `/opt/nexuspanel` |

### Ports on wireguard1

| Protocol | Port | Status |
|----------|------|--------|
| WireGuard plain | 51820/UDP | Live, E2E OK |
| AmneziaWG | 51821/UDP | Live, E2E OK (MTU 1280, no IPv6 in conf) |
| Hysteria2 | 44333/UDP | Live; home + MCI OK; Irancell/Rightel often blocked |
| TUIC | 44334/UDP | Server OK; **not viable inside Iran** (QUIC/UDP filtering) |

## Development phases completed

| Phase | Topic | Status |
|-------|-------|--------|
| Core | Xray panel, users, nodes, subscriptions | Stable |
| 0–5 | Dashboard, ops, cluster, commercial, intelligence | Done (many behind flags) |
| 6 | Tunnels Iran↔foreign, white-label | Code done; **live E2E pending** |
| 11 | WireGuard + unified `used_traffic` accounting | Done + live tested |
| 12 | AmneziaWG dual-stack on same node | Done + live tested |
| 13 | sing-box H2/TUIC + subscribe QUIC UI | Done; TUIC Iran-limited |
| **14** | **SigmaGuard app + Client API** | **API ✅ · اپ بعدی** |

## Protocol matrix (Iran reality)

| Protocol | Deployed on wireguard1 | Works in Iran |
|----------|------------------------|---------------|
| WireGuard | Yes | Medium (needs UDP) |
| AmneziaWG | Yes | Better UDP obfuscation; still UDP |
| Hysteria2 + obfs | Yes | Operator-dependent (home/MCI yes; Irancell/Rightel often no) |
| TUIC | Yes (server fixed) | **Practically no** — pure QUIC, no obfs |
| VLESS+Reality | Template ready | Best for heavy filtering — **needs live node test** |
| CDN (VLESS+WS) | Template ready | Good for heavy filtering |
| Tunnel relay→exit | Code in 0.10.0 | **Primary architecture for Iran** — E2E pending |
| SS-2022 | Code + tests | Needs provision + `client_ss2022` flag |

**Iran user recommendation:** Reality → H2 → AWG. Do not promote TUIC as primary.

## Fixed in recent session (wireguard1)

- WG NAT/FORWARD for `10.10.0.0/24` and `10.11.0.0/24`
- Client WG conf: default DNS, AWG MTU 1280, removed `::/0`
- Subscribe: separate plain/AWG links, QUIC tab, platform app deep links
- H2 link: `insecure=1` + `obfs=salamander`
- TUIC link: `allow_insecure=1`, `udp_relay_mode=native`, `alpn=h3`
- TUIC server TLS: `alpn: ["h3"]` in `node/singbox.py` (fixes ALPN handshake)
- Admin SingBox page, `/sub/{token}/info` with `hysteria2_link` / `tuic_link`
- Panel stale process cleanup via `scripts/restart_panel.sh`

## Fixed on master panel (2026-06-09 outage recovery)

- **Xray restart loop** — SS-2022 must not be hot-added via gRPC (`app/xray/serving.py`); core stderr drained (`app/xray/core.py`)
- **SS inbound mix-up** — legacy chacha20 users no longer get SS-2022 links on :8388 (`app/xray/inbound_match.py`, `scripts/fix_production_gaps.py`)
- **Reality shortId** — stable `sid=63ff9c82` in subscription/Client API (`app/subscription/share.py`)
- **Test tunnel** — `panel-loopback-e2e` disabled on production (`scripts/fix_production_gaps.py`)
- **Feature flags** — `client_api`, `api_v2`, `client_ss2022`, `cdn_fallback`, `tunneling`, `client_push` enabled (`scripts/enable_panel_flags.py`)
- **Ops** — use `systemctl restart nexuspanel.service` only; avoid `scripts/restart_panel.sh` while systemd is active

## Known remaining issues

1. **QUIC/UDP filtering in Iran** — TUIC unusable; H2 operator-dependent
2. **Self-signed TLS** on node — use SingBox → Let's Encrypt (needs DNS domain + port 80)
3. **sing-box zombie processes** on node — needs cleanup / stable restart
4. **Panel sync from CLI** fails (`xray.nodes.get()` null outside panel process) — manual deploy sometimes required
5. **Node Docker image** — `singbox.py` with `alpn` was hot-patched; image rebuild recommended
6. **Node SSH credentials** were exposed in chat — **rotate password**
7. Local `db.sqlite3` in repo is empty — production state is on live panel only
8. **Users must refresh subscription** — VLESS Reality on :8443 replaced prior links; legacy SS on :1080/:2086 unchanged

## Key files

```
app/subscription/quic.py       # hysteria2:// and tuic:// links
app/subscription/wireguard.py  # .conf export
app/singbox/                   # panel-side spec + sync
node/singbox.py                # node config render (alpn h3)
node/wireguard.py              # WG + ensure_egress_forwarding()
app/dashboard-next/.../SingBox.tsx
app/dashboard-next/.../subscribe/page.tsx
app/client/__init__.py         # network profiles + protocol priority
app/tunnel/                    # relay/exit inject
scripts/fix_production_gaps.py
scripts/enable_panel_flags.py
scripts/setup_panel_stack.py
scripts/sb_smoke_test.py
docs/CLIENT_API.md
```

## Next chat — priority backlog

1. **SigmaGuard app MVP** — Flutter shell + Rust core (repo `/opt/sigmaguard/` empty)
2. ~~Client API + app infra~~ — done (materials, structured Xray, per-protocol nodes, auto-provision, tunnel hint, gamer geo, LE, CDN flag)
3. ~~Subscribe TUIC warning~~ — done
4. ~~Let's Encrypt for H2/TUIC~~ — `POST /api/node/{id}/singbox/tls/issue` + admin UI
5. ~~sing-box zombie cleanup~~ — `node/singbox.py` + `POST /node/{id}/singbox/sync` (rebuild image still needed)
6. ~~Push FCM/APNs~~ — `app/push/sender.py` + `client_push` flag
7. ~~AWG admin download~~ — Users drawer
8. ~~Smoke scripts~~ — `tunnel_e2e.py`, `reality_smoke_test.py`, `ss2022_smoke_test.py`, `enable_panel_flags.py`
9. ~~SigmaGuard Rust core~~ — `/opt/sigmaguard/core/` (Flutter shell still pending)
10. ~~Tunnel loopback E2E~~ — disabled on prod; was test-only (`panel-loopback-e2e`)
11. ~~VLESS+Reality~~ — `VLESS TCP` inbound on :8443 with Reality (run `scripts/setup_panel_stack.py`)
12. ~~SS-2022~~ — `SS-2022` inbound on :8388 + alireza wired
13. **LE on wireguard1** — blocked: no DNS A record to `YOUR_WG_NODE_IP` (needs domain)
14. **Node image rebuild** — blocked: no SSH creds on this host (`WG_NODE_SSH_PASSWORD`)
15. **Tunnel production E2E** — needs Iran relay Xray node + foreign exit node (not loopback)

## How to continue in a new chat

Paste:

```
کانواس nexuspanel-central و docs/CENTRAL-HANDOFF.md را بخوان.
می‌خواهم ممیزی امنیتی کامل — از صف P0 در کانواس شروع کن.
نود wireguard1 (YOUR_WG_NODE_IP) · کاربر alireza.
```

Legacy detail: this file + `AUDIT-CLOSURE.md`. Visual: **only** `nexuspanel-central.canvas.tsx`.

## Tests

```bash
cd /opt/nexuspanel
python3 -m pytest -q   # 306 passed
PYTHONPATH=. python3 scripts/enable_panel_flags.py
python3 scripts/sb_smoke_test.py --node-id 1
```

**Handoff:** see [`docs/CENTRAL-HANDOFF.md`](docs/CENTRAL-HANDOFF.md) for the unified project map and security audit queue.

Enable on live panel: **System → Feature flags** → `client_api` (+ optional `cdn_fallback`, `client_ss2022`, `tunneling`).
