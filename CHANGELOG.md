# Changelog

## Unreleased

## 0.22.16 — 2026-08-01

Reseller wholesale tariffs and clearer payment statistics.

### Reseller plan tariffs (wholesale)

- New `reseller_plan_tariffs` table, separate from master retail `Plan` rows.
- Sudo UI under **Resellers → Tariffs**: create volume or unlimited wholesale tariffs with price and duration.
- API: `GET/POST /api/billing/reseller-tariffs`, `PUT/DELETE /api/billing/reseller-tariffs/{id}`.
- When a non-sudo reseller creates or renews an account that matches a tariff (data limit + duration), that wholesale price is debited from their wallet (`plan_sale`). Insufficient balance returns HTTP 402.
- Portal buy/renew matches the same wholesale tariff for the owning reseller; sudo/master is not charged. Legacy retail plan wallet debit applies only when no matching tariff exists.
- Plan edit can clear `data_limit` back to unlimited (JSON null).

### Overview payment statistics

- Payments strip includes card-to-card checkouts (not only CentralPay/Stripe/demo).
- Successful amount/count, failed/rejected/expired count, renew amount, purchase amount, and wallet top-ups.
- Reseller leaderboard includes renew/purchase/fail breakdown; platform income shows wallet spend by type and top resellers.

## 0.22.15 — 2026-08-01

Node stability release. Recommended for every install with nodes on a
high-latency path (Iran ↔ abroad) or with large WireGuard peer counts.

### Node restart loop (critical)

- After starting a node's Xray, the panel waited only 5s for its gRPC API to
  accept a channel. On a high-latency control path the TLS handshake alone
  costs 200-550ms, and a core loading thousands of WireGuard peers needs
  seconds more — so the panel concluded the start had failed, reverted the node
  to native WireGuard, and the next health tick restarted Xray again. Affected
  nodes restarted every 1-2 minutes, dropping every session each time. The wait
  is now 30s, tunable via `NODE_API_READY_TIMEOUT`.
- If that wait does expire but the core still answers over RPyC, the node is no
  longer torn down: an unreachable stats API does not mean a dead core, and
  restarting one that is actively serving users fixes nothing.

### Health check no longer starves under load

- Node health probes now run concurrently (`NODE_PROBE_CONCURRENCY`, default 8)
  instead of serially. With enough nodes on a slow path a single tick outlasted
  the job interval, so APScheduler skipped ticks (`max_instances=1`) and health
  checks effectively stopped running. Remediation stays single-threaded.

### SSH control tunnel

- Control tunnels honour each node's real SSH port instead of assuming 22, with
  the working port remembered per host and 22/2222 tried as fallbacks. Nodes on
  a non-standard SSH port previously produced a steady stream of connection
  timeouts and never got a control tunnel.
- Tunnel connect timeout cut from 15s to 8s with a single attempt, so one
  unreachable node stops blocking the jobs behind it.

## 0.22.14 — 2026-07-31

- Live 1-device exclusivity: with `device_limit=1`, WireGuard / VLESS / sing-box cannot stay online together (sticky winner + temporary protocol hold).
- Portal renew: unlimited plans (`data_limit=null`) clear the previous volume cap instead of only extending expiry.
- CentralPay relay return uses the panel public URL (multi-panel safe); Commercial Settings expose relay fields.
- Env sudo (`SUDO_USERNAME`) auto-materializes an `admins` row for billing/wallet/API keys.
- Portal payment pending TTL, resume/pay button, and receipt upload directory bootstrap.
- Plan delete: null out nullable FKs; return 409 when `user_orders` still reference the plan.

## 0.22.13 — 2026-07-31

Multi card-to-card: platform and resellers can configure several cards; portal customers and reseller top-up see a random card first and can swipe between cards.

## 0.22.12 — 2026-07-31

Ship-readiness release: payments, PWA, i18n, mobile, ops, and demo path.

### Security & payments
- Demo gateway off by default and fail-closed when disabled; Stripe requires a webhook secret when enabled.
- Card receipt uploads: magic-byte sniff, image re-encode (Pillow), PDF sanitize (pypdf), 15 MB limit, attachment/`nosniff` when serving.

### Ops & HTTPS
- Panel binds localhost-only behind nginx; unauthenticated `GET /api/health` and `/api/health/ready` return only `{ok}` (200/503).
- Docker healthcheck probes `/api/health`.

### Panel / portal UX
- Reseller panel PWA install gate + web push for invoices / top-ups / card orders.
- Users & Billing tables: card layout on mobile (≤760px).
- Master plans catalog grouped by platform vs reseller; `owner_username` on plan API.
- Master overview: per-reseller online counts; Users filter by reseller (`?admin=`).

### i18n & docs
- FA locale parity; RU/ZH billing, PWA, and commercial strings completed (other admin sections may still fall back to EN).
- Demo script: [`docs/DEMO_SCRIPT_FA.md`](docs/DEMO_SCRIPT_FA.md) + `scripts/prepare_demo_seed.py`.

## 0.22.5 — 2026-07-28

- Densify Protocols & Servers tables; compact ⋯ row menus.
- Redesign create / bulk-create user modals; empty or 0 traffic = unlimited.
- Fix panel picker: admins see pN only; resellers bind to their own domain.
- Clean up User templates bar (no split empty state).

## 0.22.4 — 2026-07-23

- In-panel node agent updates: System → Updates and per-node “Update agent” refresh the agent image over stored SSH (force re-download from GitHub/mirror, SSH upload fallback).
- Fix `refresh_agent` / `force_image_rebuild` so re-provision actually pulls a new agent image when the local tag already exists.
- WireGuard: fleet subnet auto-widen, faster Finalmask/peer sync on user create, and preferred export nodes when Finalmask lives on `wir*` hosts.

## 0.23.0 — 2026-07-20

- Scale: WireGuard peer cache (joinedload + in-process TTL) so usage/sync no longer N+1 scan tens of thousands of proxies every few seconds.
- Scale: resumable node sync — `peer_change_outbox` + `node_sync_cursors`, batch `wg_apply_batch` / Finalmask shard batches with cursor resume after disconnect.
- Scale: SQL-targeted `review_users`; safer default job intervals (usage 15s, review 30s); serving reconcile builds desired set outside the hot lock.
- Scale: Finalmask shard port reserve default 256; fleet subnet capacity auto-widen guard; RPyC fast-fail for transfer while sync holds the node lock.

## 0.22.2 — 2026-07-18

- Inbounds list: enable/disable toggle per Xray inbound (disabled inbounds stay in config, omitted from the live core).
- Per-inbound subscription settings: keep URI Path as `sub` after 3x-ui migration instead of inventing `sub-<inboundTag>`; saving the shared panel domain+path succeeds via inheritance.
- WireGuard / Finalmask tunnel and subscribe export fixes from the recent WG workstream (panel-exit sync, private-geo routing pin, single Finalmask share link, mobile `.conf` download).

## 0.21.25 — 2026-07-16

- Found the real reason "both WireGuard types" never connected even though the tunnel itself was proven healthy end-to-end (live handshake test from an external client showed 0 bytes ever received back): `schedule_finalmask_xray_reload()` was being called unconditionally from `sync_user_change()`, the generic hook that fires on *any* user lifecycle event system-wide (usage recording, quota checks, admin edits, dashboard-triggered syncs, ...) — not just actual Finalmask peer-membership changes. On a busy panel this fired every few seconds, and each firing restarted the relay's *entire* Xray core (a multi-MB Finalmask config, 10-20s to bind). Live logs confirmed the node's Xray core was restarting every ~20-90s continuously, non-stop, for as long as it had been observed — so every client handshake had a large chance of landing on a core that was mid-restart (port unbound) and no session could ever stabilize. `schedule_finalmask_xray_reload()` now fingerprints the peer set that actually gets baked into each Finalmask node's config and only restarts a node when that fingerprint actually changed since the last reload — real membership changes still reload automatically (no manual step), but the constant no-op restart storm is gone.
- Found and fixed a second, independent bug that made this worse for *new* users specifically: `wg_manager.create_peer()` (autoscale) always tried to `wg set wg0 peer ...` (hot-add) on the relay's own kernel WireGuard interface before saving the new peer — but a tunnel-delegated relay's kernel `wg0` is *intentionally* kept down (Xray/the tunnel owns the UDP port instead), so this hot-add always failed with "no such device", which rolled back the entire peer creation. New users assigned to a delegated relay could never get a working WireGuard peer record at all (confirmed live: user's `WgPeer` row never existed, `hot-add failed on wg0` logged every ~5s forever). `create_peer()` (and `toggle_peer()`) now detect tunnel delegation and, instead of touching the relay's torn-down kernel interface, commit the peer and push it straight to the real termination point (`sync_panel_exit_wireguard()` for a panel-exit tunnel, plus the normal full-sync path for a dedicated exit node).

## 0.21.24 — 2026-07-16

- Found it: `panel_exit_ready_for_node()` checked `xray.core.last_config.inbounds_by_tag` for the tunnel's exit inbound tag — but that attribute is a *curated* view built only from recognized product/proxy protocols (see `XRayConfig._resolve_inbounds`), not the raw inbound list, so an infrastructure inbound like a tunnel exit is never in it. The diagnostic added in 0.21.23 confirmed this: the live panel config had only 1 inbound in that view (its real product inbound) and the check always reported "not ready" no matter how healthy the actual tunnel was — this alone accounts for every "Xray tunnel relay not running" seen in this investigation, independent of anything else fixed in 0.21.18-0.21.22 (all real fixes, but none of them could have mattered while this check could never pass). Now reads the raw `last_config["inbounds"]` list directly, which does include the tunnel exit tag once actually booted.

## 0.21.23 — 2026-07-16

- `panel_exit_ready_for_node()` now logs exactly which tunnel-exit tags it expected vs. what it actually found on the panel's live Xray config when not ready, instead of a bare True/False — needed to pin down why this still reported "not ready" immediately after a fresh, correctly-injected tunnel apply.

## 0.21.22 — 2026-07-16

- Found the actual root cause of the panel-exit side intermittently losing its `tunnel-*-exit` inbound (which is what `panel_exit_ready_for_node` was correctly detecting all along): `sync_panel_exit_wireguard()` unconditionally calls `sync_panel_warp_egress()` on every WireGuard relay sync, which itself unconditionally restarted the panel's *entire* local Xray core every single time — even with WARP completely disabled and nothing to "re-pin" (observed live: `Panel WARP egress: enabled=False ...` followed by a full core restart, every ~15-20s on a busy panel). Re-running `apply_endpoint_tunnels` on every one of these avoidable restarts was the real source of the "Xray tunnel relay not running" flapping, not a genuinely broken relay↔panel path. `sync_panel_warp_egress()` now only restarts the core when the WARP routing state (enabled/subnets/account) actually changed since the last call.

## 0.21.21 — 2026-07-16

- Found why the breaker kept tripping even in the same beat a real tunnel-capture restart just succeeded: `relay_tunnel_xray_ready()` fed the circuit breaker itself on every call — and it's called from several purely observational spots (the periodic WG sync, the health-check probe, and the health-check's own pre-restart re-check) on top of the real attempt's own recording inside `connect_node`/`restart_node`. A single genuine failure was being counted 2-3x per cycle across these call sites, which could trip/extend the suspension even right after a real push attempt succeeded. `relay_tunnel_xray_ready()` is now purely observational (no breaker side effect) — only an actual push attempt has ground truth and is the sole source that records outcomes. It also now checks the same "is the live core actually the tunnel-capturing one" flag added in 0.21.20, instead of liveness alone.

## 0.21.20 — 2026-07-16

- Fixed a second false-positive that defeated the 0.21.19 self-heal: `connect_node`'s "keep the live Xray core, don't restart" shortcut (added to avoid OOMing small relays on a redundant Finalmask restart) only checked that *some* Xray was alive and answering `get_version()` — not that the live core was actually the tunnel-capturing one. So the proactive restart kicked off by the sync fix would immediately no-op ("keeping live Xray") against a stale native-fallback core instead of pushing the real tunnel config. The node session now tracks whether its last successful push actually included the tunnel capture (`wg_tunnel_capture_active`) and only takes the reuse shortcut when that's true.

## 0.21.19 — 2026-07-16

- Fixed the last gap keeping tunnel-delegated WireGuard from ever actually re-establishing after a failure: the periodic WireGuard sync only *observed* whether the relay's Xray had the tunnel capture bound (`relay_tunnel_xray_ready`) and logged "Xray tunnel relay not running" — it never triggered an actual config push to fix it. Nothing else was reliably doing that either, so the circuit breaker kept tripping on stale observation instead of a real failed attempt, and native WireGuard never got replaced by the tunnel again even once the network path (see 0.21.18) was healthy. The sync now kicks a real (throttled, background) restart on that relay so the fix is actually attempted automatically.

## 0.21.18 — 2026-07-16

- Found the real reason a relay's tunnel-captured WireGuard kept failing to actually establish (not just the false-positive health check fixed in 0.21.17): pushing the relay's tunnel/Finalmask Xray config (which can be 100+ KB with many peers) over the direct panel→node RPyC socket reliably dropped mid-write (`EOFError: stream has been closed`) on this Iran↔abroad route, even though the socket connected fine and the config itself was valid. `connect_node`/`restart_node` now automatically fail over to the SSH control tunnel for the retry after the first such failure, instead of endlessly retrying the same unreliable direct path.
- Fixed the SSH control-tunnel fallback being silently unusable in the first place: its key/password secret files under `/var/lib/shahkar/secrets/` were root-owned while the panel process runs as the unprivileged `shahkar` user, so every read failed with a permission error that was swallowed and reported as "no SSH access". `docker-entrypoint.sh` now reclaims ownership of that directory on every boot, so this can't silently regress again.
- SSH control-tunnel connection now tries every configured credential (key, then password) instead of only the key — a stored key file no longer permanently blocks the password fallback just because its pubkey was never installed on a particular node's `authorized_keys`.

## 0.21.17 — 2026-07-16

- Fixed the actual reason tunnel-delegated WireGuard could stay silently dead forever: the relay health probe treated "Xray answers a version" as proof the tunnel worked, even when the panel-exit side of the pipeline never came up. It now also checks that the panel's *live, booted* Xray config actually has the tunnel's exit inbound bound.
- Added an automatic delegation circuit breaker (`app/tunnel/relay.py`): after 3 consecutive tunnel-capture failures on a relay, WireGuard delegation is suspended for that node and native WireGuard is brought back up automatically — no manual DB edit, no disabling the tunnel by hand. It retries the tunnel again on its own afterwards and resumes delegation once healthy.
- Fixed a conflict the breaker would otherwise have caused: the relay's Xray config injection for the WireGuard capture (dokodemo) is now skipped whenever delegation is suspended, so Xray never again tries to bind the same UDP port native WireGuard just took back — tunnel and WireGuard can no longer fight over the same port.
- Subscription links already resolved the correct server public key from delegation state; this now also stays correct automatically while the breaker is tripped (falls back to the relay's own key/port, not the panel's canonical delegated key).

## 0.21.16 — 2026-07-16

- WireGuard autoscale sync now actually applies kernel interfaces/peers on the node (previously only opened firewall ports).
- Legacy WG interface bootstrap also creates the interface on a connected node.
- Disabled broken panel-exit tunnel stealing UDP 51820 when native WG should run on the node.

## 0.21.15 — 2026-07-16

- Provision: node→panel bootstrap HTTP is best-effort with short retries — a curl timeout no longer fails the whole install; the panel finishes registration over SSH after the agent starts.
- GitHub image download attempts use a short timeout so blocked routes fail over to the Iran mirror quickly.

## 0.21.14 — 2026-07-16

- Node packages live on GitHub Releases (`NODE_AGENT_PACKAGE_URL`); provision downloads from GitHub first (3 attempts), then the Iran HTTP mirror. The panel is no longer used as an image CDN and no longer SSH-uploads the ~135MB agent image.
- `shahkar update` can refresh the GitHub Release asset via `scripts/sync_agent_github.sh`.

## 0.21.13 — 2026-07-16

- Provision: download packages online first (SSH upload + HTTP) with 3 retries; only if that fails fall back to the Iran agent-image mirror. Docker installer also retries online 3 times before distro packages.

## 0.21.12 — 2026-07-16

- Iran agent mirror: detect domestic nodes by GeoIP of the SSH/server IP only — UI region is ignored for package download routing.

## 0.21.11 — 2026-07-16

- Iran agent-image mirror: when a node is in Iran (`region=ir` or GeoIP), provision downloads the node package from `NODE_AGENT_MIRROR_URL` (domestic) instead of SSH-uploading ~135MB from an abroad panel.
- `shahkar update` can sync the cached tarball to the mirror host via `NODE_AGENT_MIRROR_SSH`.

## 0.21.10 — 2026-07-16

- Node provision: skip re-uploading the ~135MB agent image when the node already has the same image ID (re-add / retry is seconds, not half an hour).
- Stop forcing a full HTTP `curl|docker load` refresh on every provision; image refresh is SSH-only when explicitly requested.
- Retry provision defaults to reusing the on-node image instead of `refresh_agent=true`.

## 0.21.9 — 2026-07-16

- SSH control-tunnel fallback: when direct panel→node control paths drop (common on some Iran↔abroad routes), the panel opens `ssh -L` to the node's loopback ports and dials locally instead.
- Backup/restore hardened for migrations: download bundles include DB + TLS + node control secrets; restore merges secrets, clears cert pins, and restarts the panel.
- WARP routing / WireGuard subscription export improvements; Postgres client and compose image aligned on 17.

## 0.21.8 — 2026-07-15

- WireGuard: when stack / Finalmask ports change, the panel syncs the node and opens UDP INPUT (iptables / ufw / firewalld) automatically — no manual firewall steps.
- New WG nodes seed Xray-native Finalmask (UDP 51901) by default; provision install also pre-opens 51820/51821/51901 on the host.
- UI copy no longer tells operators to open firewall ports by hand.

## 0.21.6 — 2026-07-14

- Node SSH provision: never fall back to on-node `docker build` when Docker Hub / CloudFront returns HTTP 403. The panel now uploads its prebuilt `shahkar/node` image over the SSH session (`docker load`) before starting the agent, so restricted node DCs no longer hit CloudFront blob 403 after a failed HTTP image download.
- Install curls use `-k` so a self-signed / IP panel cert does not force a failed image download.
- 3x-ui reimport: skip port-remap when the live listener belongs to the inbound tag being replaced (fixes 8443→8444 remaps on same-panel re-import).
- Branding: built-in Shahkar logo/favicon assets, `/brand` + `/favicon.ico` routes, subscription page layout refresh and i18n cleanup.

## 0.21.5 — 2026-07-14

- 3x-ui migration: stop double-counting used traffic. Shared `client_traffics` meters (and the same up/down stamped onto every inbound's client settings) were summed across inbounds, so a 50 GB user on two inbounds showed ~100 GB used. Merge with `max()` instead of sum (sqlite dump + in-memory group).

## 0.21.4 — 2026-07-14

- Agent-image cache: fall back to `/tmp` when `/var/lib/shahkar/cache` is not writable for the unprivileged panel user (same root-owned data-dir issue as the update log), so `/api/nodes/agent-image` no longer 500s during provision.

## 0.21.3 — 2026-07-14

- Node SSH provision: when Docker Hub / CloudFront returns HTTP 403 during on-node `docker build` (common in restricted DCs), load a prebuilt `shahkar/node` image from the panel (`GET /api/nodes/agent-image`) via `docker load` instead. Falls back to source bundle + build only if the panel image is unavailable.

## 0.21.2 — 2026-07-14

- Node SSH provision: when `get.docker.com` returns HTTP 403 (common from some DCs/countries), fall back to the distro Docker package (`apt`/`dnf`/`yum`) instead of failing with a misleading `curl: (22) 403` + exit 127 (`docker: command not found`) after the agent bundle already downloaded successfully.

## 0.21.1 — 2026-07-14

- Fix in-dashboard "Update" saying it succeeded while the panel kept running the old code (only the on-server manager updated correctly): the restart step wrote to `/var/lib/shahkar/update-rebuild.log`, but the panel runs unprivileged (uid 1000) and that data dir is usually `root:root 0755`, so creating the log raised `PermissionError` and aborted the restart *before* it ran — the pulled code sat on disk but the container never reloaded it. Logging is now best-effort (falls back to `/tmp`, then to no log) so the restart always fires.

## 0.21.0 — 2026-07-14

- Fix subscription serving on custom ports (e.g. migrated 3x-ui panels on `:2096/sub`) silently not working after an in-app update: the updater only ran `docker restart`, which reuses the old container's HostConfig and never applies `docker-compose.yml` changes — so a container predating the nginx bind mounts kept running with no nginx access and could never write the `:2096` vhost. Updates now detect docker-compose changes and recreate the container (via a detached sidecar that survives the swap) so new mounts/capabilities/namespaces take effect.
- Fix a missing CDN-origin TLS certificate wedging *all* of nginx: `render_nginx_site` always emitted `ssl_certificate`, so one origin domain whose cert couldn't be issued (e.g. its DNS points at the CDN edge, not this origin) made `nginx -t` fail for every vhost — taking down the panel UI and all subscription links. The origin vhost now degrades to an HTTP-only ACME placeholder until its cert lands, then a second sync pass re-renders it with TLS.

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
- `shahkar password`: reset owner login without the previous username; clearer install summary with password recovery.

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

- Fix in-dashboard update creating a wrong Docker stack (`code-*` instead of `shahkar-*`) by pinning compose project name to `shahkar`.
- Smart update paths: code-only changes → fast container restart (bind-mounted `/code`); `requirements.txt` → in-container pip; Dockerfile/entrypoint → image rebuild.
- Fix `shahkar update` CLI when `.env` uses spaced `KEY = value` lines.

## 0.12.7 — 2026-06-10

- Users page: selecting **AmneziaWG** shows the correct badge (not WireGuard).
- Persist `shahkarPanelKind` on user WireGuard proxy settings; allocate plain vs AWG peer IPs based on user intent.

## 0.12.6 — 2026-06-10

- AmneziaWG inbounds display as **amneziawg** / **AWG** in the Inbounds table (Xray JSON still uses `wireguard`).
- Persist `shahkarPanelKind` marker in inbound settings so the label survives save and reload.

## 0.12.5 — 2026-06-11

- Fix in-dashboard update: bind-mount host `docker` CLI + compose plugin; schedule detached rebuild after job reports success.
- Remove Hysteria2 / AmneziaWG preset buttons from Connection → Inbounds (use **Add inbound** instead).

## 0.12.4 — 2026-06-11

- Docker entrypoint (root → runuser) fixes `/var/lib/shahkar/xray_config.json` and `.env` permissions on start.
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
