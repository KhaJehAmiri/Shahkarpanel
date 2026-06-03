<div align="center">

<img src="https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/app/dashboard/src/assets/logo.svg" width="88" alt="NexusPanel" />

# NexusPanel

**پلتفرم حرفه‌ای مدیریت پراکسی — چندنود، وایت‌لیبل، آماده فروش**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Xray](https://img.shields.io/badge/Powered%20by-Xray--core-512BD4)](https://github.com/XTLS/Xray-core)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC)](tests/)
[![Docker](https://img.shields.io/badge/Deploy-Docker-2496ED?logo=docker&logoColor=white)](docker-compose.yml)

[English](./README.md) · **فارسی** · [简体中文](./README-zh-cn.md) · [Русский](./README-ru.md)

[نصب سریع](#-نصب-یکخطی-vps) · [معماری](#-معماری) · [امکانات](#-امکانات-کلیدی) · [امنیت و tests](#-امنیت-و-پوشه-tests-روی-گیتهاب) · [مخزن](https://github.com/KhaJehAmiri/nexuspanel)

</div>

---

## فهرست

- [NexusPanel چیست؟](#nexuspanel-چیست)
- [نصب یک‌خطی (VPS)](#-نصب-یکخطی-vps)
- [معماری](#-معماری)
- [امکانات کلیدی](#-امکانات-کلیدی)
- [وایت‌لیبل و نمایندگی](#-وایتلیبل-و-نمایندگی)
- [تونل ایران ↔ خارج](#-تونل-ایران--خارج)
- [پیش‌نیاز](#-پیشنیاز)
- [توسعه محلی](#-توسعه-محلی)
- [Docker تولید](#-docker-تولید)
- [تنظیمات](#-تنظیمات)
- [امنیت و پوشه `tests` روی گیت‌هاب](#-امنیت-و-پوشه-tests-روی-گیتهاب)
- [لایسنس](#-لایسنس)

---

## NexusPanel چیست؟

پنل کنترل **تمام‌عیار** برای زیرساخت Xray: از مدیریت کاربر و نود تا **فروش، ریسلر، HA، اتوماسیون و تحلیل ترافیک** — در یک محصول واحد با داشبورد مدرن React.

| برای چه کسی؟ | چه مشکلی حل می‌کند؟ |
|--------------|---------------------|
| ارائه‌دهنده سرویس (ISP/VPN) | چند نود، مانیتورینگ، failover |
| فروشنده / ریسلر | وایت‌لیبل، کیف پول، نود اختصاصی با تخفیف |
| تیم فنی | API v2، Rule Engine، Workflow، پلاگین |

> قابلیت‌های پیشرفته پیش‌فرض **خاموش** هستند و از **Setup wizard** (`/dashboard/#/manage/`) یا Feature Flag روشن می‌شوند.

---

## نصب یک‌خطی (VPS)

روی **اوبونتو / دبیان** تازه، با کاربر **root**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
```

<details>
<summary><strong>اسکریپت نصب چه کار می‌کند؟</strong></summary>

| مرحله | عملیات |
|--------|--------|
| 1 | نصب Docker و git |
| 2 | Clone از `KhaJehAmiri/nexuspanel` → `/opt/nexuspanel` |
| 3 | ساخت `.env` (رمز ادمین، JWT، `NODE_BOOTSTRAP_TOKEN`) |
| 4 | Build و اجرای پنل با Docker Compose |
| 5 | Build ایمیج `nexuspanel/node` برای افزودن نود با SSH |
| 6 | چاپ آدرس داشبورد و مشخصات ورود |

</details>

**بعد از نصب**

| مورد | آدرس / دستور |
|------|----------------|
| داشبورد | `http://SERVER_IP:8000/dashboard/` |
| وایت‌لیبل / Setup | `http://SERVER_IP:8000/dashboard/#/manage/` |
| مدیریت | `nexuspanel status` · `logs` · `update` · `backup` |

---

## معماری

```mermaid
flowchart TB
  subgraph clients [کلاینت‌ها]
    U[کاربر نهایی]
  end

  subgraph panel [NexusPanel — یک نصب]
    API[FastAPI + داشبورد React]
    DB[(PostgreSQL / SQLite)]
    R[Redis — Event Bus / HA]
    API --> DB
    API --> R
  end

  subgraph nodes [نودها]
    N1[نود مالک]
    N2[نود نماینده BYO]
    NR[relay ایران]
    NE[exit خارج]
  end

  U -->|سابسکرایب| API
  API -->|کنترل Xray| N1
  API --> N2
  U -->|اتصال| NR
  NR -->|تونل رمزنگاری| NE
  NE -->|اینترنت| Internet((خارج))
```

---

## امکانات کلیدی

<table>
<tr>
<th>لایه</th>
<th>امکانات</th>
<th>وضعیت</th>
</tr>
<tr>
<td><strong>هسته</strong></td>
<td>کاربر، اینباند، هاست، نود، سابسکرایب، تلگرام</td>
<td>پایدار</td>
</tr>
<tr>
<td><strong>زیرساخت</strong></td>
<td>PostgreSQL، Event Bus، بکاپ، Feature Flag، لاگ JSON</td>
<td>فاز ۰</td>
</tr>
<tr>
<td><strong>عملیات</strong></td>
<td>Prometheus، Grafana، Rule Engine، پلاگین، Webhook</td>
<td>فاز ۱</td>
</tr>
<tr>
<td><strong>کلاستر</strong></td>
<td>Auto-heal، bootstrap نود، failover، OpenTelemetry</td>
<td>فاز ۲</td>
</tr>
<tr>
<td><strong>تجاری</strong></td>
<td>RBAC، پلن، کیف پول، فاکتور، API v2</td>
<td>فاز ۳</td>
</tr>
<tr>
<td><strong>مقیاس</strong></td>
<td>HA Leader، Smart Routing، Workflow</td>
<td>فاز ۴</td>
</tr>
<tr>
<td><strong>هوشمندی</strong></td>
<td>تشخیص مصرف غیرعادی، پیش‌بینی اتمام حجم، Marketplace</td>
<td>فاز ۵</td>
</tr>
<tr>
<td><strong>وایت‌لیبل</strong></td>
<td>Tenant، برند، نود SSH، تونل relay/exit، نصب یک‌خطی</td>
<td>فاز ۶</td>
</tr>
</table>

---

## وایت‌لیبل و نمایندگی

یک نصب پنل → **چند نماینده** با برند جدا، **بدون سرور دوم اجباری**:

| قابلیت | توضیح |
|--------|--------|
| **Tenant** | جداسازی ادمین، کاربر، پلن و نود per نماینده |
| **Branding** | لوگو، رنگ، عنوان پنل، لینک پشتیبانی |
| **نود با IP+پسورد** | نماینده سرور خودش را می‌دهد؛ پنل agent را نصب می‌کند |
| **تخفیف BYO** | ترافیک روی نود خود نماینده ارزان‌تر حساب می‌شود |
| **داشبورد Reseller** | منوی White-label در سایدبار |

---

## تونل ایران ↔ خارج

برای پروتکل‌هایی که **مستقیم** از ایران به سرور خارج پایدار نیستند:

```text
کلاینت  →  نود relay (ایران)  →  تونل Reality/WS/gRPC  →  نود exit (خارج)  →  اینترنت
```

تعریف تونل در پنل → ساخت خودکار قطعات Xray برای relay و exit.

---

## پیش‌نیاز

| محیط | نیازمندی |
|--------|-----------|
| **VPS نصب** | لینوکس، root، پورت 8000 باز، 2GB+ RAM پیشنهادی |
| **توسعه** | Python 3.10+، Xray (یا stub در تست) |
| **تولید** | PostgreSQL 14+، Redis 7+ (برای HA) |

---

## توسعه محلی

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

## Docker تولید

```bash
docker compose -f docker-compose.postgres.yml up -d --build
docker compose -f docker-compose.monitoring.yml up -d
```

داده: `/var/lib/nexuspanel`

---

## تنظیمات

| متغیر | کاربرد |
|--------|--------|
| `SQLALCHEMY_DATABASE_URL` | SQLite (dev) / PostgreSQL (prod) |
| `REDIS_URL` | Event Bus + HA |
| `NODE_BOOTSTRAP_TOKEN` | ثبت خودکار نود |
| `NODE_AGENT_IMAGE` | ایمیج نود (`nexuspanel/node:latest`) |
| `PANEL_PUBLIC_ADDRESS` | آدرس عمومی برای نودهای نماینده |
| `HA_ENABLED` | چند instance پنل |

جزئیات: [`.env.example`](.env.example)

---

## امنیت و پوشه `tests` روی گیت‌هاب

### آیا `tests/` باید روی گیت باشد؟

**بله — نه تنها مشکلی ندارد، بلکه توصیه می‌شود.**

| سوال | پاسخ |
|------|------|
| آیا رمز یا `.env` داخل tests است؟ | **خیر** — فقط دیتابیس موقت و xray ساختگی |
| آیا با نصب پنل، tests اجرا می‌شود؟ | **خیر** — فقط برای توسعه‌دهنده و CI |
| آیا حذف tests امن‌تر است؟ | **خیر** — کیفیت و regression بدون تست پایین می‌آید |

فایل `tests/conftest.py` یک SQLite موقت در `/tmp` می‌سازد و هیچ اطلاعات production را لمس نمی‌کند.

جزئیات: [SECURITY.md](SECURITY.md) · [tests/README.md](tests/README.md)

**هرگز commit نکنید:** `.env` واقعی، dump دیتابیس، کلید TLS خصوصی (همه در `.gitignore` هستند).

---

## لایسنس

این پروژه تحت **[AGPL-3.0](LICENSE)** منتشر شده است (مشتق از اکوسیستم Xray/Marzban-class panels). استفاده شبکه‌ای (SaaS) نیازمند رعایت شرایط AGPL برای کاربران نهایی است.

---

## مشارکت

[CONTRIBUTING.md](CONTRIBUTING.md) — Issues و PR: [github.com/KhaJehAmiri/nexuspanel](https://github.com/KhaJehAmiri/nexuspanel)
