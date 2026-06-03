<p align="center">
  <strong style="font-size: 2rem; letter-spacing: -0.03em;">NexusPanel</strong>
</p>

<p align="center">
  Профессиональная платформа управления прокси — мультинод, коммерция, observability.<br/>
  На базе <a href="https://github.com/XTLS/Xray-core">Xray-core</a>.
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./README-fa.md">فارسی</a> ·
  <a href="./README-zh-cn.md">简体中文</a> ·
  <a href="./README-ru.md">Русский</a>
</p>

---

## Обзор

**NexusPanel** — панель управления Xray-инфраструктурой: реселлеры, биллинг, кластер, умная маршрутизация, автоматизация и аналитика трафика.

| Слой | Возможности |
|------|-------------|
| **Ядро** | Пользователи, inbounds, hosts, ноды, подписки, Telegram |
| **Фундамент** | PostgreSQL, Redis event bus, бэкапы, feature flags |
| **Операции** | Prometheus, Grafana, rules, plugins, workflows |
| **Масштаб** | HA leader election, health нод, failover, smart routing |
| **Коммерция** | RBAC, планы, wallet/invoice, API v2 + API keys |
| **Интеллект** | Heavy users, прогноз исчерпания трафика, marketplace |

Новые функции по умолчанию **выключены** (feature flags).

---

## Требования

- Linux (рекомендуется)
- Python 3.10+
- [Xray-core](https://github.com/XTLS/Xray-core)
- Опционально: PostgreSQL 14+, Redis 7+
- Опционально: Docker

---

## Быстрый старт

```bash
git clone https://github.com/nexuspanel/nexuspanel.git
cd nexuspanel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python3 main.py
```

Панель: `http://127.0.0.1:8000/dashboard/`

```bash
python3 nexuspanel-cli.py admin create --sudo
```

---

## Docker

```bash
docker compose -f docker-compose.postgres.yml up -d --build
docker compose -f docker-compose.monitoring.yml up -d
```

Данные: `/var/lib/nexuspanel`

---

## Конфигурация

См. `.env.example`: `SQLALCHEMY_DATABASE_URL`, `REDIS_URL`, `HA_ENABLED`, `METRICS_TOKEN`, `BACKUP_DIR`, `NEXUSPANEL_ADMIN_PASSWORD`.

Флаги: `billing`, `api_v2`, `smart_routing`, `workflows`, `traffic_intelligence`, `plugin_marketplace`.

---

## CLI

```bash
python3 nexuspanel-cli.py admin create --sudo
python3 nexuspanel-cli.py user list
python3 nexuspanel-cli.py backup create
```

---

## API

- **v1**: `/api/*` (OAuth2 admin token)
- **v2**: `/api/v2/*` (пагинация, `X-API-Key`, flag `api_v2`)

Документация: `/docs` при `DOCS=True`.

---

## systemd

```bash
sudo bash install_service.sh
sudo systemctl enable --now nexuspanel
```

---

## Тесты

```bash
python3 -m pytest -q
```

---

## Лицензия

MIT — [LICENSE](LICENSE).

---

## Участие

[CONTRIBUTING.md](CONTRIBUTING.md) · [github.com/nexuspanel/nexuspanel](https://github.com/nexuspanel/nexuspanel)
