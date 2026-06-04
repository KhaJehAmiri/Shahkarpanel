<div align="center">

<img src="https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/docs/logo.svg" width="88" alt="NexusPanel" />

# NexusPanel

**Профессиональная платформа управления прокси — мультинод, white-label, готова к продаже**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC)](tests/)

[English](./README.md) · [فارسی](./README-fa.md) · [简体中文](./README-zh-cn.md) · **Русский**

</div>

---

## Установка одной командой (VPS)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
```

Панель: `http://IP:8000/dashboard/` · Флаги: `#/system`

---

## Возможности

| Слой | Описание |
|------|----------|
| Ядро | Пользователи, ноды, подписки, Telegram |
| Инфраструктура | PostgreSQL, Redis, бэкапы, feature flags |
| Операции | Prometheus, Grafana, rules, plugins |
| Коммерция | RBAC, billing, API v2 |
| White-label | Tenants, брендинг, SSH-ноды, туннели relay→exit |

---

## Безопасность: папка `tests/` на GitHub

**Да, `tests/` должна быть в репозитории** — это автотесты (pytest), без секретов и без данных клиентов. Подробнее: [SECURITY.md](SECURITY.md).

---

## Лицензия

[AGPL-3.0](LICENSE) · [Репозиторий](https://github.com/KhaJehAmiri/nexuspanel)
