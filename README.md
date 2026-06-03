<p align="center">
  <strong style="font-size: 2rem; letter-spacing: -0.03em;">NexusPanel</strong>
</p>

<p align="center">
  Professional proxy management platform — multi-node, commercial-ready, observability-first.<br/>
  Powered by <a href="https://github.com/XTLS/Xray-core">Xray-core</a>.
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./README-fa.md">فارسی</a> ·
  <a href="./README-zh-cn.md">简体中文</a> ·
  <a href="./README-ru.md">Русский</a>
</p>

---

## Overview

**NexusPanel** is a full-stack control plane for operating Xray-based proxy infrastructure at scale: resellers, billing, clustering, smart routing, automation, and traffic intelligence — in one panel.

| Layer | Highlights |
|--------|------------|
| **Core** | Users, inbounds, hosts, nodes, subscriptions, Telegram bot |
| **Foundation** | PostgreSQL, Redis event bus, backups, feature flags, structured logs |
| **Operations** | Prometheus metrics, Grafana, rules, plugins, workflows |
| **Scale** | HA leader election, node health/latency, failover, smart routing |
| **Commercial** | RBAC, plans, billing wallet, API v2 + API keys |
| **Intelligence** | Heavy-user detection, exhaustion prediction, plugin marketplace |

New capabilities are **off by default** behind feature flags until you enable them.

---

## Requirements

- Linux (recommended)
- Python 3.10+
- [Xray-core](https://github.com/XTLS/Xray-core)
- Optional: PostgreSQL 14+, Redis 7+ (HA / production)
- Optional: Docker & Docker Compose

---

## Quick start (development)

```bash
git clone https://github.com/KhaJehAmiri/nexuspanel.git
cd nexuspanel

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum set SQLALCHEMY_DATABASE_URL and secrets

alembic upgrade head
python3 main.py
```

Open the dashboard (default): `http://127.0.0.1:8000/dashboard/`

Create a sudo admin:

```bash
python3 nexuspanel-cli.py admin create --sudo
```

---

## Production stack (Docker)

PostgreSQL + Redis + panel:

```bash
docker compose -f docker-compose.postgres.yml up -d --build
```

Monitoring (Prometheus + Grafana):

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Data directory (default): `/var/lib/nexuspanel`

---

## Configuration

Copy `.env.example` → `.env`. Important variables:

| Variable | Purpose |
|----------|---------|
| `SQLALCHEMY_DATABASE_URL` | `sqlite:///…` (dev) or `postgresql://…` (prod) |
| `REDIS_URL` | Event bus + HA leader election |
| `HA_ENABLED` | Multi-instance singleton jobs |
| `METRICS_TOKEN` | Prometheus scrape auth |
| `BACKUP_DIR` | Backup archives (`/var/lib/nexuspanel/backups`) |
| `NEXUSPANEL_ADMIN_PASSWORD` | Non-interactive CLI admin password |

Enable features via API (sudo) or DB:

- `prometheus_metrics`, `plugins`, `rule_engine`, `auto_healing`
- `billing`, `api_v2`, `smart_routing`, `workflows`
- `traffic_intelligence`, `plugin_marketplace`

```bash
# Example: enable billing + v2 API globally (sudo token required)
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' \
  https://your-panel/api/feature-flags/billing
```

---

## CLI

```bash
python3 nexuspanel-cli.py --help
python3 nexuspanel-cli.py admin create --sudo
python3 nexuspanel-cli.py user list
python3 nexuspanel-cli.py backup create
```

Install system-wide:

```bash
sudo ln -sf $(pwd)/nexuspanel-cli.py /usr/local/bin/nexuspanel-cli
sudo chmod +x nexuspanel-cli.py nexuspanel-cli
nexuspanel-cli completion install
```

---

## API

- **v1**: existing `/api/*` routes (admin OAuth2 bearer token).
- **v2**: `/api/v2/*` — paginated, API-key friendly (`X-API-Key` or bearer). Requires `api_v2` flag.

OpenAPI docs when `DOCS=True`: `/docs` and `/redoc`.

---

## Systemd service

```bash
sudo bash install_service.sh
sudo systemctl enable nexuspanel
sudo systemctl start nexuspanel
```

---

## Testing

```bash
python3 -m pytest -q
python3 -m ruff check app/ tests/
```

CI runs tests on SQLite and validates Alembic migrations against PostgreSQL.

---

## Project layout

```
app/           FastAPI backend, jobs, plugins, billing, intelligence
app/dashboard/ React + Chakra UI (NexusPanel theme)
cli/           Typer CLI modules
monitoring/    Prometheus & Grafana provisioning
tests/         Pytest suite
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome on [github.com/KhaJehAmiri/nexuspanel](https://github.com/KhaJehAmiri/nexuspanel).

### One-line install (VPS)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
```
