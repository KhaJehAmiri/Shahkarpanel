<p align="center">
  <strong style="font-size: 2rem; letter-spacing: -0.03em;">NexusPanel</strong>
</p>

<p align="center">
  پلتفرم حرفه‌ای مدیریت پراکسی — چندنود، آماده فروش و مانیتورینگ.<br/>
  مبتنی بر <a href="https://github.com/XTLS/Xray-core">Xray-core</a>.
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./README-fa.md">فارسی</a> ·
  <a href="./README-zh-cn.md">简体中文</a> ·
  <a href="./README-ru.md">Русский</a>
</p>

---

## معرفی

**NexusPanel** یک پنل کنترل کامل برای زیرساخت پراکسی مبتنی بر Xray است: ریسلر، صورتحساب، کلاستر، مسیریابی هوشمند، اتوماسیون و تحلیل ترافیک — در یک محصول.

| لایه | امکانات |
|------|---------|
| **هسته** | کاربر، اینباند، هاست، نود، سابسکرایب، ربات تلگرام |
| **زیرساخت** | PostgreSQL، Event Bus با Redis، بکاپ، Feature Flag، لاگ JSON |
| **عملیات** | Prometheus، Grafana، Rule Engine، پلاگین، Workflow |
| **مقیاس** | HA با Leader Election، سلامت نود، Failover، Smart Routing |
| **تجاری** | RBAC، پلن، کیف پول و فاکتور، API v2 و کلید API |
| **هوشمندی** | تشخیص کاربر سنگین، پیش‌بینی اتمام حجم، بازار پلاگین |

قابلیت‌های جدید پیش‌فرض **خاموش** هستند و با Feature Flag روشن می‌شوند.

---

## پیش‌نیاز

- لینوکس (پیشنهادی)
- Python 3.10+
- [Xray-core](https://github.com/XTLS/Xray-core)
- اختیاری: PostgreSQL 14+، Redis 7+ (تولید / HA)
- اختیاری: Docker و Docker Compose

---

## راه‌اندازی سریع (توسعه)

```bash
git clone https://github.com/nexuspanel/nexuspanel.git
cd nexuspanel

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# ویرایش .env

alembic upgrade head
python3 main.py
```

داشبورد: `http://127.0.0.1:8000/dashboard/`

ساخت ادمین سودو:

```bash
python3 nexuspanel-cli.py admin create --sudo
```

---

## استقرار با Docker

```bash
docker compose -f docker-compose.postgres.yml up -d --build
docker compose -f docker-compose.monitoring.yml up -d
```

مسیر داده پیش‌فرض: `/var/lib/nexuspanel`

---

## تنظیمات

فایل `.env.example` را کپی کنید. متغیرهای مهم:

| متغیر | کاربرد |
|--------|--------|
| `SQLALCHEMY_DATABASE_URL` | SQLite (توسعه) یا PostgreSQL (تولید) |
| `REDIS_URL` | Event Bus و انتخاب Leader در HA |
| `HA_ENABLED` | چند نمونه پنل روی یک DB |
| `METRICS_TOKEN` | احراز Prometheus |
| `BACKUP_DIR` | مسیر بکاپ |
| `NEXUSPANEL_ADMIN_PASSWORD` | رمز CLI بدون تعامل |

Feature Flagها: `billing`, `api_v2`, `smart_routing`, `workflows`, `traffic_intelligence`, `plugin_marketplace` و غیره.

---

## CLI

```bash
python3 nexuspanel-cli.py admin create --sudo
python3 nexuspanel-cli.py user list
python3 nexuspanel-cli.py backup create
```

نصب سراسری:

```bash
sudo ln -sf $(pwd)/nexuspanel-cli.py /usr/local/bin/nexuspanel-cli
nexuspanel-cli completion install
```

---

## API

- **v1**: مسیرهای `/api/*` با توکن ادمین.
- **v2**: `/api/v2/*` با صفحه‌بندی؛ هدر `X-API-Key` یا Bearer (نیاز به flag `api_v2`).

با `DOCS=True`: مستندات در `/docs`.

---

## سرویس systemd

```bash
sudo bash install_service.sh
sudo systemctl enable nexuspanel
sudo systemctl start nexuspanel
```

---

## تست

```bash
python3 -m pytest -q
```

---

## ساختار پروژه

```
app/           بک‌اند FastAPI
app/dashboard/ رابط React (تم NexusPanel)
cli/           ابزار خط فرمان
monitoring/    Prometheus و Grafana
tests/         تست‌ها
```

---

## لایسنس

MIT — فایل [LICENSE](LICENSE).

---

## مشارکت

[CONTRIBUTING.md](CONTRIBUTING.md) — مخزن: [github.com/nexuspanel/nexuspanel](https://github.com/nexuspanel/nexuspanel).
