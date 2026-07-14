# Changelog

## 0.20.0 — 2026-07-14

- 3x-ui migration: block silently hijacking another panel's subscription route. Many panels can share one port (e.g. every panel on `:2096/sub`) as long as each has its own domain; importing a panel whose `(host, path)` is already owned by a *different* panel — or a panel with an empty `subURI` (route collapses to "any domain" + `/sub/`) — now fails with a clear message instead of upserting in place and merging two panels' users onto one link. Re-importing the *same* panel still updates in place.
- UI: fix the user-stat popover (Limited / On hold / etc.) squishing rows into an unreadable sliver when a status bucket had many users — rows are pinned so the list scrolls instead of collapsing.

## 0.19.0 — 2026-07-14

- Fix in-app update not taking effect: the panel recreated itself with `compose up --force-recreate` from *inside* the container, so stopping the old container killed the orchestrator before the new one started — leaving the panel on the OLD in-memory code after a successful pull. Restart is now a single atomic `docker restart <cid>` the daemon completes even after the CLI dies (and it preserves `pip`-mode installs).
- Fix bulk delete still failing on some panels with a `subscription_token_aliases` not-null violation: purge alias rows explicitly before deleting users, independent of the ORM cascade config.
- Fix Overview stats freeze / repeated "maximum number of running instances" scheduler spam: WireGuard usage collection triggered the RPyC `remote` connect (with lock + retries) merely while detecting a node's transport type — now detected on the class without dialing, so a down WG node can't stall the 5s usage job.

## 0.18.0 — 2026-07-14

- Bulk delete (expired/disabled / all): run large deletes as a background job with status polling so reverse-proxy timeouts no longer show "Server error" while the delete actually completes.
- Swallow Xray ``TagNotFoundError`` on hot user-remove (orphan inbound tags left after 3x-ui migration no longer spam exception threads).

## 0.17.0 — 2026-07-14

- Updates modal: cache the update check (stale-while-revalidate, 5 min TTL) so the Install button enables immediately instead of waiting on a blocking `git fetch`/GitHub round-trip on every open.
- Cap `git fetch` at 12s and shorten GitHub HTTPS timeouts to 8s on slow/filtered networks.
- Add `?force=true` for the explicit "Check for updates" button; keep Install enabled during background re-checks.

## 0.16.0 — 2026-07-14

- Fix "delete expired/disabled" and "delete all" users: defer subscription-alias removal to the DB cascade and purge un-cascaded analytics/order rows (node protocol usage, client probes/telemetry/devices, user orders) before delete, so bulk delete no longer aborts on a foreign-key/not-null violation.
- Detach (instead of drop) nullable user references on delete: payment history and dedicated-IP pool survive.

## 0.15.0 — 2026-07-14

- 3x-ui migration: run imports in a background job with live progress polling (instant API response, no proxy timeout).
- 3x-ui migration: preserve source `email` (3x-ui username) in user `note` for panel search.
- 3x-ui migration: merge multi-inbound clients by subId; per-user savepoints; faster bulk import.
- Reseller `max_total_traffic`: block new users and auto-suspend when cap is exceeded.
- `nexus password`: reset owner login without the previous username; clearer install summary with password recovery.

## 0.14.0 — 2026-07-07

- Fix ruff lint in admin/user routers (unused imports, isort).
- CI: drop `tests/` from public-repo lint path; skip pytest when tests are not shipped.

## 0.12.13 — 2026-06-10

- Dashboard update: `--force-recreate` panel container after git pull so Python loads the new version.
- UI polls `/api/system/version` until the target version is live before reloading the page.
- Sync `install-meta.json` from `VERSION` on panel startup.

## 0.12.12 — 2026-06-10

- Fix fast dashboard updates: use `docker compose restart` (not `up -d`) so the Python process reloads after git pull.
- `/api/system` version reads `VERSION` from disk so sidebar and Updates tab stay in sync.

## 0.12.11 — 2026-06-10

- E2E verification release for the dashboard update pipeline (no functional changes).

## 0.12.10 — 2026-06-10

- Reorder update steps: **pull before backup** so Docker PostgreSQL backup fix is available before dump runs.
- Backup step is non-fatal when dump fails (update continues).

## 0.12.9 — 2026-06-10

- Fix pre-update backup when `pg_dump` is not in the panel image (dump via `docker compose exec postgres`).
- Includes v0.12.8 update system fixes (compose project name, smart fast restart).

## 0.12.8 — 2026-06-10

- Fix in-dashboard update creating a wrong Docker stack (`code-*` instead of `nexuspanel-*`) by pinning compose project name to `nexuspanel`.
- Smart update paths: code-only changes → fast container restart (bind-mounted `/code`); `requirements.txt` → in-container pip; Dockerfile/entrypoint → image rebuild.
- Fix `nexuspanel update` CLI when `.env` uses spaced `KEY = value` lines.

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
