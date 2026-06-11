# Changelog

## 0.12.7 — 2026-06-10

- Users page: selecting **AmneziaWG** shows the correct badge (not WireGuard).
- Persist `nexusPanelKind` on user WireGuard proxy settings; allocate plain vs AWG peer IPs based on user intent.

## 0.12.6 — 2026-06-10

- AmneziaWG inbounds display as **amneziawg** / **AWG** in the Inbounds table (Xray JSON still uses `wireguard`).
- Persist `nexusPanelKind` marker in inbound settings so the label survives save and reload.

## 0.12.5 — 2026-06-11

- Fix in-dashboard update: bind-mount host `docker` CLI + compose plugin; schedule detached rebuild after job reports success.
- Remove Hysteria2 / AmneziaWG preset buttons from Connection → Inbounds (use **Add inbound** instead).

## 0.12.4 — 2026-06-11

- Docker entrypoint (root → runuser) fixes `/var/lib/nexuspanel/xray_config.json` and `.env` permissions on start.
- AmneziaWG preset and Save pre-generate `secretKey` in the dashboard before PUT `/core/config`.

## 0.12.3 — 2026-06-10

- Fix AmneziaWG/WireGuard inbound save: auto-generate `secretKey`, map `amneziawg` → `wireguard`, strip invalid stream settings.
- Run `xray run -test` before persisting core config; surface validation errors as HTTP 400.
- Inbound editor: Generate WireGuard keys button; fix `xray_config.json` permissions for Docker uid 1000.

## 0.12.2 — 2026-06-10

- Fix `PermissionError: /code/.env` when bind-mounting the app dir into Docker (chown uid 1000).
- Skip unreadable `.env` in `load_dotenv` (Compose `env_file` already injects vars).
- Silence APScheduler `pkg_resources` deprecation warning; pin setuptools `<81`.

## 0.12.1 — 2026-06-10

- Dashboard update detection via GitHub HTTPS when git is unavailable in Docker.
- One-click in-dashboard updates: bind-mount app dir, docker.sock, git + docker CLI in container.
- Sidebar and Overview update alerts use `update_available` semver comparison.

## 0.12.0 — 2026-06-10

- User create wizard: AmneziaWG protocol card + fixed protocol picker grid CSS.
- Shell installer (3x-ui style) as default; progress bar fix under `set -u`.
- WireGuard API validation accepts nodes with plain WG or AmneziaWG enabled.

## 0.11.0 — 2026-06-10

- Professional web installer wizard (language, HTTPS, branding, live progress).
- In-place panel updates from any page with automatic reload after install.
- Localized “What’s new” popup after each update (en / fa / ru / zh).
- Sidebar version strip with update alert for sudo admins.
- Secret dashboard path, reseller branding isolation, live data polling.

## 0.10.0 — 2026-06-06

- Tunnels now actually deploy: relay/exit Xray fragments are injected per
  endpoint on connect/restart, with a `POST /tunnels/{id}/apply` to push them.
- Either tunnel end can be a node or the panel's own local core, so an Iran
  panel can be the relay (add only a foreign exit) and vice versa.
- Reality keypairs are generated automatically (`xray x25519`) on tunnel create.
- Relay user inbounds are pinned to the tunnel outbound; WireGuard is carried
  inside Reality via a dokodemo-door UDP capture on the relay.
- Add-node flow can create a tunnel with this panel in one step.
- Backend hardening: fixed the `SQLALCHEMY_MAX_OVERFLOW` env typo (with
  fallback), surfaced Xray restart errors after upgrade, replaced bare excepts,
  used `XRAY_EXECUTABLE_PATH` for the local version probe, and added a guard
  against concurrent panel updates.
- Frontend: guaranteed Vazirmatn/Inter fonts in the build, completed ru/zh
  translations (full parity), localized shared UI strings, and set html
  lang/dir from the persisted language before paint.

## 0.9.4 — 2026-06-04

- Panel updates show semver (v0.9.x) instead of git hashes.
- Clean update progress steps; no shell/npm log dump in the UI.
- Restart works without Docker (systemd or scripts/restart_panel.sh).

## 0.9.2 — 2026-06-04

- Test release for in-panel updates (System → Updates).
- User import wizard: Marzban, 3x-ui, CSV, share links.
- Xray version UI on Infrastructure and System tabs.

## 0.9.1

- Full user import from other panels.

## 0.9.0

- System polish phase: deployment info, updates API, feature flags i18n.
