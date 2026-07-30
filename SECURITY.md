# Security policy

## Reporting vulnerabilities

If you discover a security issue, please **do not** open a public GitHub issue with exploit details.
Contact the repository owner privately (GitHub Security Advisories or direct message).

## What must never be committed

| Item | Status in this repo |
|------|---------------------|
| `.env` with real secrets | **Gitignored** — use `.env.example` only |
| Production database dumps | Not tracked |
| TLS private keys / JWT secrets | Generated on install, not in git |
| SSH passwords / node credentials | Under `/var/lib/shahkar/secrets/` on the server only |
| User passwords | Never in source |
| Internal handoff / audit / e2e scripts | **Gitignored** — stay on development servers |

## Is the `tests/` folder on this public GitHub repo?

**No.** The full pytest suite, smoke/e2e scripts, and internal ops docs are listed in `.gitignore` and are **not** pushed to the public install repository (same approach as Marzban / 3x-ui style release trees).

| Question | Answer |
|----------|--------|
| Are tests on GitHub? | **No** — run locally or on a private CI clone |
| What runs in GitHub Actions? | Lint + Alembic migrations on PostgreSQL |
| Passwords or real IPs in examples? | Placeholders only (`example.com`, RFC 5737 docs IPs) |

## Runtime secrets layout (on the server)

Keep secrets **outside** the git checkout (`/opt/shahkar`):

| Path | Purpose |
|------|---------|
| `/opt/shahkar/.env` | Non-secret panel config (Uvicorn, CORS, titles) |
| `/var/lib/shahkar/.env` | Runtime secrets (DB URL, JWT, bootstrap/metrics tokens) |
| `/var/lib/shahkar/secrets/` | Panel → node SSH key / optional password file |

Fresh installs split these automatically via `shahkar install` / `scripts/setup_env.sh`.

## Production hardening checklist

- Change the default admin password immediately after install.
- Set strong `NODE_BOOTSTRAP_TOKEN` and `METRICS_TOKEN` in the runtime `.env`.
- Use PostgreSQL + Redis for production; restrict network access to DB/Redis.
- Enable HTTPS in front of the panel (`shahkar https` or your reverse proxy).
- Revoke unused Personal Access Tokens and API keys.
- Run panel updates via `shahkar update` from tagged releases.
- Never paste real IPs, passwords, or `.env` contents into public issues or commits.
