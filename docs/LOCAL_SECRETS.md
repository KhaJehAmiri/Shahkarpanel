# Local secrets (never commit)

This repo is **source code only**. Production IPs, passwords, keys, and node data stay on each server.

## Two `.env` files (M16)

| Path | Purpose |
|------|---------|
| `/opt/nexuspanel/.env` | **Repo config** — UVicorn, CORS, Xray paths, panel title. Bind-mounted to `/code`; must not contain secrets. |
| `/var/lib/nexuspanel/.env` | **Runtime secrets** — Postgres/Redis URLs, admin hash, node tokens. Mounted at the same path in Docker; **not** under `/code`. |

Docker Compose loads both (`env_file: [.env, /var/lib/nexuspanel/.env]`); runtime values override repo defaults. The panel also loads both at startup via `config._load_env_file()`.

Migrate an existing single-file `.env`:

```bash
python3 scripts/migrate_runtime_secrets.py
python3 scripts/migrate_runtime_secrets.py --rotate-tokens   # also rotate bootstrap/metrics tokens
```

Fresh install: `scripts/setup_env.sh` or `nexuspanel install` writes the split automatically.

## Runtime secrets directory (SSH keys)

Panel → node SSH credentials live under:

```
/var/lib/nexuspanel/secrets/
```

| File | Purpose |
|------|---------|
| `nexuspanel_node` | Ed25519 private key for panel → node SSH |
| `nexuspanel_node.pub` | Matching public key |
| `wg_node_ssh` | Node root password fallback for provisioning scripts |

Create the directory on the host (mode `700`) and bootstrap with:

```bash
python3 scripts/setup_node_ssh_access.py --host YOUR_NODE_IP
```

## Gitignored (local only)

| Path | Purpose |
|------|---------|
| `.env` | Repo config (may exist locally; no secrets after M16 migration) |
| `/var/lib/nexuspanel/.env` | Runtime secrets (on server only) |
| `.wg_node_ssh` | **Legacy** — migrate to `/var/lib/nexuspanel/secrets/wg_node_ssh` |
| `.ssh/` | **Legacy** — migrate to `/var/lib/nexuspanel/secrets/nexuspanel_node` |

Copy `.env.example` → `.env` and use `setup_env.sh` on the server. Never commit secrets.

## Scripts read secrets from disk or env

- `WG_NODE_HOST` — optional; otherwise first WireGuard node from panel DB
- `WG_NODE_SSH_PASSWORD` — optional; otherwise `wg_node_ssh` in secrets dir
- `NODE_SSH_KEY_FILE` — optional; default `/var/lib/nexuspanel/secrets/nexuspanel_node`
- `WG_NODE_SSH_PASSWORD_FILE` — optional; default `/var/lib/nexuspanel/secrets/wg_node_ssh`
- `NEXUSPANEL_SECRETS_DIR` — optional; default `/var/lib/nexuspanel/secrets`

## What goes in git

- Application code, Dockerfiles, migrations, tests
- `.env.example` with placeholder comments only
- Docs with `YOUR_PANEL_IP` / `YOUR_WG_NODE_IP` placeholders

## If you already pushed a secret

1. Rotate the password/key immediately.
2. Remove from history (`git filter-repo` or BFG) before the next public push.
3. Confirm with `git log -p -S 'secret_fragment'`.
