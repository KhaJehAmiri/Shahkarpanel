# NexusPanel audit closure (2026-06)

All planned audit phases **13–16** and UI parity items are implemented in `master`.

## Security (backend)

| ID | Status |
|----|--------|
| SEC-001 | `SUDO_PASSWORD_HASH` preferred; plaintext ignored when hash set |
| SEC-002–008, 010–012, 015, 019–023 | Done in prior commits |
| SEC-009 | Login webhooks redact password (`report.login`) |
| SEC-010 | Bootstrap rate limit |
| SEC-013 | `NODE_SSL_VERIFY` optional strict TLS |
| SEC-014/025 | Node agent: set `SSL_CLIENT_CERT_FILE` on panel + node (mTLS for RPyC/REST) |
| SEC-016 | `POST /api/system/jwt/rotate` + `clear_secret_key_cache` |
| SEC-020 | WS logs: bearer header only |
| SEC-024 | `NODE_CONTROL_SECRET` on node REST |
| SEC-026–029 | Subscription guards, JSON bootstrap, tenant validation, SSH `RejectPolicy` default |
| SEC-030 | Realtime `bandwidth_scope` for resellers |

## UI (dashboard-next only)

- Overview: realtime, nodes usage, top users
- Users: CRUD, reset/revoke, templates, create from template
- System: flags, backup **restore**, API keys, admins CRUD, setup wizard
- Billing: plans edit, wallet credit (sudo)
- Resellers: tenant PATCH
- Infra: hosts advanced, tunnels PATCH + config
- Automation: marketplace, rules/workflows flags
- Analytics: smart routing, intelligence
- Subscribe: en/fa/ru/zh

## Deploy

```bash
./scripts/setup_env.sh          # once — random admin password + bcrypt hash
./build_dashboard.sh
./scripts/deploy_production.sh  # builds, then runs scripts/setup_https.sh
```

## P0 hardening — now built into install (2026-06-10)

These were previously "operator tasks"; they are now automated and secure by
default so every fresh install gets them:

| Item | Where it's handled |
|------|--------------------|
| No default password (`changeme` removed) | `scripts/setup_env.sh` + `nexuspanel.sh write_env` generate a random password, store only the bcrypt `SUDO_PASSWORD_HASH` |
| HTTPS reverse proxy | `scripts/setup_https.sh` (nginx + Let's Encrypt **IP or domain** cert, auto-renew) — invoked by the installer and `deploy_production.sh` |
| App port not public | `UVICORN_HOST=127.0.0.1` by default; firewall opens 80/443 (and detected SSH port), never the app port |
| Dashboard URL | `https://<domain-or-ip>/dashboard/` everywhere (installer output, doctor, docs) |
| Secret rotation | `POST /api/system/jwt/rotate` (SEC-016) invalidates leaked admin/subscription tokens |

## Tests

`pytest` — 306 passed, 1 skipped. CI: ruff on security modules + full test suite.

## Remaining operator tasks (not code)

1. **Node mTLS** (the one P0 step needing node access). Materials are generated
   on the panel by:
   ```bash
   sudo ./scripts/generate_node_mtls.sh /var/lib/nexuspanel/certs/mtls
   ```
   Then on each node set `SSL_CLIENT_CERT_FILE=/var/lib/nexuspanel/certs/mtls/ca.pem`,
   restart the agent, and finally set `NODE_SSL_VERIFY=True` on the panel.
   (Do not flip `NODE_SSL_VERIFY` before the node has the CA, or live nodes drop.)
2. PostgreSQL restore: import `restore-db.sql` manually after backup restore API on non-SQLite.
3. Local run (no Docker): `./scripts/run_local.sh`
