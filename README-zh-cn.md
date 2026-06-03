<p align="center">
  <strong style="font-size: 2rem; letter-spacing: -0.03em;">NexusPanel</strong>
</p>

<p align="center">
  专业代理管理平台 — 多节点、商业化、可观测。<br/>
  基于 <a href="https://github.com/XTLS/Xray-core">Xray-core</a>。
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./README-fa.md">فارسی</a> ·
  <a href="./README-zh-cn.md">简体中文</a> ·
  <a href="./README-ru.md">Русский</a>
</p>

---

## 概述

**NexusPanel** 是面向 Xray 代理基础设施的控制平面：经销商、计费、集群、智能路由、自动化与流量分析一体化。

| 层级 | 功能 |
|------|------|
| **核心** | 用户、入站、主机、节点、订阅、Telegram |
| **基础** | PostgreSQL、Redis 事件总线、备份、特性开关 |
| **运维** | Prometheus、Grafana、规则引擎、插件、工作流 |
| **规模** | HA 选主、节点健康、故障转移、智能路由 |
| **商业** | RBAC、套餐、钱包/账单、API v2 |
| **智能** | 重用户检测、流量耗尽预测、插件市场 |

新功能默认**关闭**，通过 feature flag 启用。

---

## 环境要求

- Linux（推荐）
- Python 3.10+
- [Xray-core](https://github.com/XTLS/Xray-core)
- 可选：PostgreSQL 14+、Redis 7+
- 可选：Docker

---

## 快速开始

```bash
git clone https://github.com/nexuspanel/nexuspanel.git
cd nexuspanel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python3 main.py
```

面板：`http://127.0.0.1:8000/dashboard/`

```bash
python3 nexuspanel-cli.py admin create --sudo
```

---

## Docker 部署

```bash
docker compose -f docker-compose.postgres.yml up -d --build
docker compose -f docker-compose.monitoring.yml up -d
```

数据目录：`/var/lib/nexuspanel`

---

## 配置

参见 `.env.example`：`SQLALCHEMY_DATABASE_URL`、`REDIS_URL`、`HA_ENABLED`、`METRICS_TOKEN`、`BACKUP_DIR`、`NEXUSPANEL_ADMIN_PASSWORD`。

特性开关：`billing`、`api_v2`、`smart_routing`、`workflows`、`traffic_intelligence`、`plugin_marketplace`。

---

## 命令行

```bash
python3 nexuspanel-cli.py admin create --sudo
python3 nexuspanel-cli.py user list
python3 nexuspanel-cli.py backup create
```

---

## API

- **v1**：`/api/*`（管理员 Bearer）
- **v2**：`/api/v2/*`（分页，`X-API-Key`，需 `api_v2`）

`DOCS=True` 时访问 `/docs`。

---

## systemd

```bash
sudo bash install_service.sh
sudo systemctl enable --now nexuspanel
```

---

## 测试

```bash
python3 -m pytest -q
```

---

## 许可证

MIT — [LICENSE](LICENSE)。

---

## 贡献

[CONTRIBUTING.md](CONTRIBUTING.md) · [github.com/nexuspanel/nexuspanel](https://github.com/nexuspanel/nexuspanel)
