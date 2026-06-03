<div align="center">

<img src="https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/app/dashboard/src/assets/logo.svg" width="88" alt="NexusPanel" />

# NexusPanel

**Professional proxy control plane — multi-node, white-label, commercial-ready**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Xray](https://img.shields.io/badge/Powered%20by-Xray--core-512BD4)](https://github.com/XTLS/Xray-core)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC)](tests/)
[![Docker](https://img.shields.io/badge/Deploy-Docker-2496ED?logo=docker&logoColor=white)](docker-compose.yml)

**English** · [فارسی](./README-fa.md) · [简体中文](./README-zh-cn.md) · [Русский](./README-ru.md)

[Quick install](#-one-line-install-vps) · [Architecture](#-architecture) · [Features](#-feature-matrix) · [Security & tests](#-security-is-the-tests-folder-on-github) · [Repository](https://github.com/KhaJehAmiri/nexuspanel)

</div>

---

## Table of contents

- [What is NexusPanel?](#what-is-nexuspanel)
- [One-line install (VPS)](#-one-line-install-vps)
- [Architecture](#-architecture)
- [Feature matrix](#-feature-matrix)
- [White-label & resellers](#-white-label--resellers)
- [Iran ↔ foreign tunnels](#-iran--foreign-tunnels)
- [Requirements](#-requirements)
- [Development](#-development)
- [Production Docker](#-production-docker)
- [Configuration](#-configuration)
- [Security: is `tests/` on GitHub safe?](#-security-is-the-tests-folder-on-github)
- [License](#-license)

---

## What is NexusPanel?

A full-stack **Xray control plane**: users, nodes, subscriptions, **resellers, billing, HA, automation, and traffic intelligence** — with a modern React dashboard.

| Audience | Value |
|----------|--------|
| Service provider | Multi-node ops, metrics, failover |
| Reseller | White-label brand, wallet, BYO nodes at discount |
| Engineering | API v2, rules, workflows, plugins |

> Advanced features are **off by default** — enable via **Setup wizard** (`/dashboard/#/manage/`) or feature flags.

---

## One-line install (VPS)

On a fresh **Ubuntu / Debian** server as **root**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
```

<details>
<summary><strong>What the installer does</strong></summary>

| Step | Action |
|------|--------|
| 1 | Install Docker & git |
| 2 | Clone `KhaJehAmiri/nexuspanel` → `/opt/nexuspanel` |
| 3 | Generate `.env` (admin password, JWT, bootstrap token) |
| 4 | Build & run panel via Docker Compose |
| 5 | Build `nexuspanel/node` image for SSH provisioning |
| 6 | Print dashboard URL and credentials |

</details>

| Item | Value |
|------|--------|
| Dashboard | `http://SERVER_IP:8000/dashboard/` |
| White-label / Setup | `http://SERVER_IP:8000/dashboard/#/manage/` |
| Manage | `nexuspanel status` · `logs` · `update` · `backup` |

---

## Architecture

```mermaid
flowchart TB
  subgraph clients [Clients]
    U[End user]
  end

  subgraph panel [NexusPanel single install]
    API[FastAPI + React dashboard]
    DB[(PostgreSQL / SQLite)]
    R[Redis Event Bus / HA]
    API --> DB
    API --> R
  end

  subgraph nodes [Nodes]
    N1[Owner node]
    N2[Reseller BYO node]
    NR[Relay in-country]
    NE[Exit abroad]
  end

  U -->|subscription| API
  API -->|Xray control| N1
  API --> N2
  U --> NR
  NR -->|encrypted tunnel| NE
  NE --> Internet((Internet))
```

---

## Feature matrix

| Layer | Highlights | Phase |
|-------|------------|-------|
| **Core** | Users, inbounds, hosts, nodes, subs, Telegram | Stable |
| **Foundation** | PostgreSQL, event bus, backups, flags, JSON logs | 0 |
| **Operations** | Prometheus, Grafana, rules, plugins, webhooks | 1 |
| **Cluster** | Auto-heal, node bootstrap, failover, OTEL | 2 |
| **Commercial** | RBAC, plans, wallet, invoices, API v2 | 3 |
| **Scale** | HA leader, smart routing, workflows | 4 |
| **Intelligence** | Anomaly detection, exhaustion forecast, marketplace | 5 |
| **White-label** | Tenants, branding, SSH nodes, tunnels, installer | 6 |

---

## White-label & resellers

One panel install → **multiple resellers**, each with their own brand — **no mandatory second server**:

| Feature | Description |
|---------|-------------|
| **Tenant** | Scoped admins, users, plans, nodes |
| **Branding** | Logo, colors, panel title, support URL |
| **SSH node add** | Reseller provides IP + password; panel installs agent |
| **BYO discount** | Cheaper usage rate on reseller-owned nodes |
| **UI** | **White-label** section in dashboard sidebar |

---

## Iran ↔ foreign tunnels

When direct client → foreign server is unstable:

```text
Client → relay node (in-country) → Reality/WS/gRPC tunnel → exit node (abroad) → Internet
```

Define tunnels in the panel; Xray fragments are generated for relay and exit.

---

## Requirements

| Environment | Needs |
|-------------|--------|
| **VPS install** | Linux, root, port 8000 open, 2GB+ RAM recommended |
| **Development** | Python 3.10+, Xray (or test stub) |
| **Production** | PostgreSQL 14+, Redis 7+ (for HA) |

---

## Development

```bash
git clone https://github.com/KhaJehAmiri/nexuspanel.git
cd nexuspanel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python3 main.py
```

```bash
python3 nexuspanel-cli.py admin create --sudo
python3 -m pytest -q
```

---

## Production Docker

```bash
docker compose -f docker-compose.postgres.yml up -d --build
docker compose -f docker-compose.monitoring.yml up -d
```

Data: `/var/lib/nexuspanel`

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `SQLALCHEMY_DATABASE_URL` | SQLite (dev) / PostgreSQL (prod) |
| `REDIS_URL` | Event bus + HA |
| `NODE_BOOTSTRAP_TOKEN` | Node self-registration |
| `NODE_AGENT_IMAGE` | Node image (`nexuspanel/node:latest`) |
| `PANEL_PUBLIC_ADDRESS` | Public URL for provisioned nodes |
| `HA_ENABLED` | Multi-instance panel |

See [`.env.example`](.env.example).

---

## Security: is the `tests/` folder on GitHub?

### Should `tests/` be in the repo?

**Yes — it is recommended and not a security risk.**

| Question | Answer |
|----------|--------|
| Passwords or `.env` in tests? | **No** — temp SQLite + fake xray stub only |
| Does production install run tests? | **No** — developers & CI only |
| Safer to delete tests? | **No** — you lose regression coverage |

`tests/conftest.py` uses a temporary database under `/tmp` and never touches production data.

Details: [SECURITY.md](SECURITY.md) · [tests/README.md](tests/README.md)

**Never commit:** real `.env`, DB dumps, private TLS keys (all in `.gitignore`).

---

## License

Licensed under **[AGPL-3.0](LICENSE)**. Network use (SaaS) must comply with AGPL obligations to end users.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — [github.com/KhaJehAmiri/nexuspanel](https://github.com/KhaJehAmiri/nexuspanel)
