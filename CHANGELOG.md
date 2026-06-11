# Changelog

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
