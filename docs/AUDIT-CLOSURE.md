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
./scripts/setup_env.sh          # once
# edit .env
./build_dashboard.sh
./scripts/deploy_production.sh
```

## Tests

`pytest` — 155+ passed. CI: ruff on security modules + full test suite.

## Remaining operator tasks (not code)

1. Set production secrets in `.env` (never commit).
2. Install panel TLS (reverse proxy).
3. Configure node `SSL_CLIENT_CERT_FILE` for mTLS.
4. PostgreSQL restore: import `restore-db.sql` manually after backup restore API on non-SQLite.
