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
| User passwords | Never in source or tests |

## Is the `tests/` folder safe on GitHub?

**Yes — it should stay in the repository.** This is standard for open-source and private projects alike.

The `tests/` directory contains **automated unit/integration tests** (pytest), not customer data or production configuration:

- `conftest.py` creates a **temporary** SQLite database under `/tmp` and a **fake** `xray` shell stub so CI does not need real infrastructure.
- Test files assert billing math, feature flags, tunnels, tenants, etc. — no hard-coded passwords or API keys.
- Running `pytest` on a server **does not** install or expose the panel to the internet.

Keeping `tests/` on GitHub improves security overall: every change is verified before release.

## Production hardening checklist

- Change default admin password immediately after install.
- Set strong `NODE_BOOTSTRAP_TOKEN` and `METRICS_TOKEN` in `.env`.
- Use PostgreSQL + Redis for production; restrict network access to DB/Redis.
- Enable HTTPS in front of the panel (reverse proxy).
- Revoke unused Personal Access Tokens and API keys.
- Run panel updates via `nexuspanel update` from tagged releases.
