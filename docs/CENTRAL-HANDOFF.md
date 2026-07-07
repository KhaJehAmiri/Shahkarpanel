# NexusPanel — مرجع مرکزی پروژه (Handoff)

> **آخرین به‌روزرسانی:** ۱۰ ژوئن ۲۰۲۶  
> **نسخه:** 0.10.0  
> **کانواس:** [`nexuspanel-central.canvas.tsx`](/root/.cursor/projects/opt/canvases/nexuspanel-central.canvas.tsx) — **تنها منبع بصری**

---

## شروع سریع (چت جدید)

**همیشه هر دو را بخوان:** [`nexuspanel-central.canvas.tsx`](/root/.cursor/projects/opt/canvases/nexuspanel-central.canvas.tsx) + **این فایل**.

سیستم **دو وجهی** است — در چت جدید اول مشخص کن کدام وجه (یا هر دو) مدنظر است.

### ممیزی امنیتی (پنل + API)
```
کانواس nexuspanel-central و docs/CENTRAL-HANDOFF.md را بخوان.
سیستم دو وجهی است: (۱) NexusPanel عمومی /sub/ (۲) SigmaGuard /api/v2/client/.
می‌خواهم ممیزی امنیتی کامل — از صف P0 شروع کن (هر دو لایه).
مسیر: /opt/nexuspanel · پنل: http://YOUR_PANEL_IP:8000
```

### طراحی / ساخت SigmaGuard (اپ)
```
/opt/SIGMAGUARD_HANDOFF.md و /opt/WORKSPACE.md را بخوان.
وجه ۱: پنل AGPL برای اپراتورها با /sub/ · وجه ۲: SigmaGuard اختصاصی ما.
همچنین بخوان: /opt/sigmaguard/SIGMAGUARD_APP_BRIEF.md و docs/CLIENT_API.md
مسیر پنل: /opt/nexuspanel · اپ: /opt/sigmaguard (شامل wire/ برای UDP)
```

---

## مدل دو وجهی — **هستهٔ درک پروژه**

**یک بک‌اند، دو مصرف‌کننده.** بدون fork کد.

```
                    ┌─────────────────────────────────┐
                    │     NexusPanel (FastAPI)        │
                    │  dashboard · users · nodes · Xray │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
   وجه ۱ — عمومی (AGPL)                      وجه ۲ — SigmaGuard (اختصاصی ما)
   اپراتور / فروشنده                         استفاده شخصی + محصول premium
              │                                           │
   کلاینت: v2rayNG · Hiddify · WG · AmneziaWG   کلاینت: اپ SigmaGuard (Flutter+Rust)
   مسیر:   /sub/{token}/ · /subscribe          مسیر:   /api/v2/client/*
   flag:   همیشه فعال                          flag:   client_api (System → Feature flags)
   کاربر:  هر نصب‌کنندهٔ پنل                   کاربر:  portal_enabled + پروفایل Gamer/Trader/Regular
```

| | **وجه ۱ — NexusPanel عمومی** | **وجه ۲ — SigmaGuard** |
|---|------------------------------|-------------------------|
| **هدف** | فروش VPN با اپ‌های رایج بازار | اپ یک‌دکمه‌ای هوشمند؛ انتخاب خودکار پروتکل/نود |
| **مخاطب** | اپراتورها، ریسلرها، نصب Marzban-style | تیم ما / مشتری premium |
| **کلاینت** | v2rayNG، Hiddify، sing-box، Clash، WireGuard، AmneziaWG | Flutter UI + Rust core |
| **API** | `/sub/{token}/` · QR · `.conf` WG/AWG | `/api/v2/client/*` · negotiate · probe · telemetry |
| **پروفایل** | — | Gamer / Trader / Regular (`client_profile`) |
| **Repo** | `/opt/nexuspanel` (AGPL · منتشرشدنی) | `/opt/sigmaguard` (اپ + `wire/` اختصاصی) |
| **مستندات** | `docs/PUBLIC_DEPLOYMENT.md` | `SIGMAGUARD_APP_BRIEF.md` · `docs/CLIENT_API.md` · `/opt/SIGMAGUARD_HANDOFF.md` |
| **وضعیت** | production · subscribe زنده | Client API ~۹۰٪ · اپ Flutter ~۱۰٪ (G05) |

**قانون طلایی:** هر چیزی که Client API سرو می‌دهد، از همان subscription/config لایه ۱ قابل ساخت است. اپراتور عمومی **هرگز** به SigmaGuard نیاز ندارد؛ SigmaGuard لایهٔ **افزایشی** روی همان پنل است.

---

## این پروژه چیست؟

**NexusPanel** کنترل‌پلن VPN/پروکسی (AGPL-3.0، تکامل Marzban) — **پلتفرم مشترک** هر دو وجه:

| لایه | مسیر | وجه | وضعیت |
|------|------|-----|--------|
| داشبورد ادمین | `/dashboard/` | هر دو | Next.js · ۵ منو + ۳ هاب |
| سابسکرایب عمومی | `/sub/{token}/` | **۱** | v2rayNG · Hiddify · WG · H2/TUIC |
| Client API | `/api/v2/client/*` | **۲** | بک‌اند آماده · اپ Flutter/Rust بعدی |
| نودها | Docker agent | هر دو | Xray · WG/AWG · sing-box |

---

## زیرساخت زنده (این دیپلوی)

| مورد | مقدار |
|------|--------|
| پنل | `https://YOUR_PANEL_IP/dashboard/` (nginx TLS · LE IP-cert · :8000 فقط localhost) |
| لینک ساب | `https://YOUR_PANEL_IP/sub/{token}/` — `XRAY_SUBSCRIPTION_URL_PREFIX` ست شد؛ fallback به `PANEL_PUBLIC_ADDRESS` در `public_url.py`؛ نصب (`setup_https.sh`) خودکار ست می‌کند |
| مخزن | `/opt/nexuspanel` |
| DB تولید | `/var/lib/nexuspanel/db.sqlite3` |
| نود تست | `wireguard1` · id=1 · `YOUR_WG_NODE_IP` |
| کاربر تست | `alireza` · id=5 · UUID VLESS WS فعال |
| pytest | **306 passed**, 1 skipped |

### پورت‌های کلیدی (پنل / wireguard1)

| سرویس | پورت | یادداشت |
|--------|------|---------|
| VLESS Reality | 8443/TCP | inbound `VLESS TCP` |
| VLESS WS | 2095/TCP | path `/vless` |
| SS legacy | 1080, 2086 | |
| SS-2022 | 8388 | hot-sync غیرفعال — فقط restart |
| WG plain | 51820/UDP | E2E OK |
| AWG | 51821/UDP | E2E OK |
| Hysteria2 | 44333/UDP | ایران: اپراتور-وابسته |
| TUIC | 44334/UDP | ایران: عملاً غیرقابل استفاده |

---

## معماری (خلاصه)

```
وجه ۱  کلاینت عمومی (v2rayNG/WG/…)  →  /sub/{token}/  →  share · quic · wireguard
وجه ۲  اپ SigmaGuard               →  /api/v2/client/* →  negotiate · probe · materials
                    ↘                              ↙
                     پنل :8000  FastAPI + jobs + Xray stdin
                              ↓
                     نودها: WG/AWG + sing-box (H2/TUIC) + Xray relay
```

**ایران (هر دو وجه):** Reality → H2 → AWG → تونل relay→exit. TUIC پیشنهاد نشود.

### SigmaGuard — خلاصه طراحی اپ (جزئیات در APP_BRIEF)

| موضوع | مقدار |
|--------|--------|
| UI | یک دکمه Connect · پینگ · badge پروفایل — **بدون** نمایش نام پروتکل/سرور |
| پروفایل‌ها | Gamer (latency) · Trader (IP ثابت · dedip) · Regular (auto-switch) |
| موتور | Rust (`/opt/sigmaguard/core/`) · Flutter shell بعدی |
| جریان | detect شبکه → negotiate → probe نودها → connect → failover خاموش |
| MVP باز | VLESS+Reality · H2 · AWG · Android/iOS |

---

## UI داشبورد (وضعیت فعلی)

| بخش | مسیر | توضیح |
|-----|------|--------|
| خانه | `/overview` | گیج CPU/RAM · Health checklist · آمار زنده |
| کاربران | `/users` | ویزارد ۳ مرحله · چند پروتکل · حالت حرفه‌ای |
| سرورها | `/servers?tab=` | nodes · WG · H2/TUIC · tunnels · dedip |
| پروتکل و لینک | `/connection?tab=` | inbounds · hosts · Xray (expert) |
| کسب‌وکار | `/business?tab=` | billing · resellers · analytics · automation |
| تنظیمات | `/system` | عمومی · نگهداری · دسترسی + expert mode |

**Inbound editor:** فقط VLESS/VMess/Trojan/SS در حالت عادی؛ http/socks/dokodemo/wg-Xray فقط در **حالت حرفه‌ای**.

---

## کارهای انجام‌شده (جمع‌بندی جلسات)

### ممیزی و بک‌اند
- SS-2022 cipher/PSK در editor · inbound/user import · tags validation
- Xray restart loop (SS-2022 gRPC) · Reality shortId پایدار
- Node edit · node groups · SingBox همه نودها · Tunnels nav gating
- Billing wallet sudo · invoice UI · automation edit · i18n fa/en

### UI
- ناوبری ۵ آیتم + ۳ هاب · legacy redirect
- Overview گرافیکی · System گروه‌بندی · User wizard چند پروتکل
- Inbound editor تفکیک product/advanced

### Client API / subscribe
- `/api/v2/client/*` · materials · auto-provision · LE endpoint
- Subscribe TUIC warning · AWG download · sing-box sync API

---

## نواقص باقی‌مانده (غیر امنیتی)

| ID | موضوع | شدت |
|----|--------|-----|
| D09 | Tunnel E2E production ایران↔خارج | بحرانی (ops) |
| G03 | rebuild node image (singbox zombie fix) | بالا |
| G04 | LE روی wireguard1 (نیاز DNS) | متوسط |
| G05 | SigmaGuard Flutter app | بالا |
| C06 | Resellers ProvisionTab ناقص | متوسط |
| F09 | i18n ru/zh ناقص | متوسط |
| — | ~~`POST /user/{u}/revoke_sub` → 500~~ | ✅ رفع شد (۱۰ ژوئن) |

---

## صف ممیزی امنیتی — **چت بعدی**

این بخش هدف اصلی چت جدید است. کد SEC-* در `docs/AUDIT-CLOSURE.md` بسیاری را «Done» علامت زده؛ **بازبینی زنده لازم است.**

### P0 — اپراتور / فوری  ✅ (۱۰ ژوئن ۲۰۲۶ — انجام و در نصب کدگذاری شد)
1. ✅ رمز sudo/admin پیش‌فرض (`changeme`) — rotate شد + JWT rotate؛ نصب حالا رمز تصادفی + bcrypt می‌سازد (`setup_env.sh` / `nexuspanel.sh`)
2. ⏳ SSH نود لو رفته — rotate (ops؛ خارج از کد)
3. ⏳ mTLS نود: CA ساخته شد (`/var/lib/nexuspanel/certs/mtls`)؛ flip `NODE_SSL_VERIFY` پس از deploy `ca.pem` روی نود
4. ✅ HTTPS reverse proxy: `scripts/setup_https.sh` (nginx + LE — IP یا domain · auto-renew)؛ پورت ۸۰۰۰ localhost-only
5. ✅ `.env` production — untracked تأیید شد؛ نصب با مجوز 600 و اسرار تصادفی می‌سازد

### P1 — کد (بازبینی · به‌روز ۱۰ ژوئن)
| ID | موضوع | مسیر | وضعیت |
|----|--------|------|--------|
| revoke_sub | `VLESSSettings not a mapping` + `portal_password` | `crud.revoke_user_sub` | ✅ رفع شد — rotate مستقیم proxies؛ زنده 200 |
| sub پس از revoke | توکن stable (epoch-0) بعد از revoke برای همیشه 404 می‌شد | `models/user.py` | ✅ توکن از `sub_revoked_at+1` re-key می‌شود؛ زنده 200 |
| sub URL پشت proxy | `public_subscription_url` به `http://IP:8000` مرده اشاره می‌کرد | `public_url.py` + `.env` | ✅ prefix ست شد + fallback به `PANEL_PUBLIC_ADDRESS`؛ در نصب خودکار شد |
| API scopes | enforce روی `/api/v2` | `v2.py → require_v2_scope` | ✅ تأیید شد (قبلاً انجام) |
| Backup | اسرار در archive | `backup.py` | ✅ `.env` پیش‌فرض خارج · sudo-only · مجوز 600/700 |
| RBAC-001 | reseller به آمار sudo-level | `analytics`/`intelligence`/`metrics` | ✅ scoped/sudo-gated؛ `routing.py` سخت‌شد (nodes:read) |
| RBAC-002 | infra/tunnels برای non-sudo → 403 | `tunnel.py` | ✅ همه `check_sudo_admin` |
| SEC-014/025 | RPyC/REST mTLS اجباری | `node/` | ⏳ CA آماده؛ نیاز deploy روی نود + `NODE_SSL_VERIFY=True` |

### P2 — سخت‌سازی
- CSP / HSTS headers
- Rate limit login/bootstrap
- Subscription token HMAC truncation
- Failed login webhook redaction (SEC-009 claimed done — verify)
- Dependency bumps (urllib3, python-multipart)

### روش پیشنهادی چت امنیت
1. `pytest` baseline (306)
2. Bugbot + Security Review روی branch
3. اسکن دستی: auth · RBAC · subscription · node bootstrap · backup restore
4. تست زنده با admin غیر sudo
5. گزارش FINDINGS با ID · شدت · PoC · fix

---

## فایل‌های کلیدی

### وجه ۱ — پنل عمومی + subscribe
```
app/subscription/            # guards · share · quic · wireguard — مسیر /sub/
app/xray/serving.py          # hot-sync users · SS-2022 no gRPC
app/dashboard-next/src/panel/  # UI اپراتور
docs/PUBLIC_DEPLOYMENT.md    # راهنمای اپراتور بدون اپ اختصاصی
```

### وجه ۲ — SigmaGuard + Client API
```
app/routers/client_v2.py     # /api/v2/client/*
app/client/__init__.py       # network profiles · protocol priority
docs/CLIENT_API.md           # قرارداد API
/opt/sigmaguard/
  SIGMAGUARD_APP_BRIEF.md    # طراحی کامل UI/UX · state machine · roadmap
  core/src/lib.rs            # Rust MVP scaffold
  app/README.md              # Flutter shell (هنوز create نشده)
```

### مشترک · ops · امنیت
```
app/routers/user.py          # CRUD · revoke_sub
app/tunnel/                  # dokodemo inject
node/singbox.py              # H2/TUIC · alpn
scripts/enable_panel_flags.py   # client_api flag
scripts/fix_production_gaps.py
docs/AUDIT-CLOSURE.md
SECURITY.md
```

---

## دستورات

```bash
cd /opt/nexuspanel
python3 -m pytest -q                    # 306 passed
./build_dashboard.sh
systemctl restart nexuspanel.service    # ترجیحاً؛ نه restart_panel.sh همزمان
python3 scripts/enable_panel_flags.py
sudo scripts/setup_https.sh             # nginx + TLS (IP) — یا --domain panel.example.com
sudo scripts/setup_https.sh --domain panel.example.com --email you@example.com
# tls renew (خودکار): systemctl list-timers certbot-renew.timer
```

---

## کانواس‌های قدیمی (منسوخ)

همه به **`nexuspanel-central.canvas.tsx`** ادغام شدند:

`nexuspanel-master-status` · `nexuspanel-full-audit` · `nexuspanel-audit-gaps` · `nexuspanel-expert-audit` · `nexuspanel-audit-registry` · `nexuspanel-backend-brief` · `nexuspanel-full-provision` · `nexuspanel-release-control` · `nexuspanel-system-polish` · `nexuspanel-reseller-portal` · `inbound-outbound-audit` · `phase11-wireguard` · `marzban-roadmap` · `sigmaguard-roadmap`

---

## مستندات مرتبط

| فایل | وجه | نقش |
|------|-----|-----|
| **docs/CENTRAL-HANDOFF.md** | هر دو | **مرجع مرکزی — مدل دو وجهی** |
| docs/PUBLIC_DEPLOYMENT.md | ۱ | اپراتور · subscribe · بدون اپ اختصاصی |
| docs/CLIENT_API.md | ۲ | قرارداد `/api/v2/client/*` |
| `/opt/SIGMAGUARD_HANDOFF.md` | ۲ | **مرجع اکوسیستم SigmaGuard — چت جدید از اینجا** |
| `/opt/sigmaguard/SIGMAGUARD_APP_BRIEF.md` | ۲ | طراحی کامل اپ · UX · roadmap |
| `/opt/sigmaguard/README.md` | ۲ | ساختار repo اپ |
| docs/PROJECT_STATUS.md | هر دو | تاریخچه فازها |
| docs/AUDIT-CLOSURE.md | هر دو | SEC 13–16 |
| SECURITY.md | هر دو | checklist امنیت |
