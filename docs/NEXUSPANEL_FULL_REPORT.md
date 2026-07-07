# NexusPanel — گزارش فنی جامع و کامل

> **نسخه پنل:** `0.13.0`  ·  **مسیر:** `/opt/nexuspanel`  ·  **مجوز:** AGPL-3.0
> **تاریخ گزارش:** ۳۰ ژوئن ۲۰۲۶
> **هدف این فایل:** مرجع کامل و دقیق همه بخش‌ها و امکانات NexusPanel — برای تسلط کامل در هر چت/جلسه جدید.

این گزارش از بررسی زندهٔ کد تهیه شده است. برای handoff اکوسیستم SigmaGuard، فایل `/opt/SIGMAGUARD_HANDOFF.md` را هم ببین.

---

## فهرست

1. [نمای کلی و معماری](#1-نمای-کلی-و-معماری)
2. [Bootstrap و چرخه اجرا](#2-bootstrap-و-چرخه-اجرا)
3. [مدل احراز هویت، RBAC و API Key](#3-مدل-احراز-هویت-rbac-و-api-key)
4. [Routerها و API کامل](#4-routerها-و-api-کامل)
5. [مدل داده (دیتابیس)](#5-مدل-داده-دیتابیس)
6. [پروتکل‌ها و موتورها (Xray / sing-box / WireGuard)](#6-پروتکلها-و-موتورها)
7. [Subscription و فرمت‌های کلاینت](#7-subscription-و-فرمتهای-کلاینت)
8. [Client API v2 و SigmaGuard](#8-client-api-v2-و-sigmaguard)
9. [معماری نود (Node Agent)](#9-معماری-نود-node-agent)
10. [تونل relay→exit (ایران)](#10-تونل-relayexit-ایران)
11. [داشبورد (Frontend)](#11-داشبورد-frontend)
12. [Jobها (کارهای پس‌زمینه)](#12-jobها-کارهای-پسزمینه)
13. [ماژول‌های تجاری (Billing/Tenant/Portal/Intelligence)](#13-ماژولهای-تجاری)
14. [زیرساخت داخلی (Events/Rules/Workflows/Plugins/Services)](#14-زیرساخت-داخلی)
15. [امنیت](#15-امنیت)
16. [Deployment و Ops](#16-deployment-و-ops)
17. [اسکریپت‌ها](#17-اسکریپتها)
18. [Monitoring](#18-monitoring)
19. [تست‌ها](#19-تستها)
20. [Config کامل و Feature Flagها](#20-config-کامل-و-feature-flagها)
21. [تاریخچه نسخه](#21-تاریخچه-نسخه)
22. [وضعیت فعلی و کارهای باز](#22-وضعیت-فعلی-و-کارهای-باز)

---

## 1. نمای کلی و معماری

**NexusPanel** یک کنترل‌پلین VPN/پروکسی است (تکامل پنل‌های Marzban-style) که یک بک‌اند واحد دارد و **دو مصرف‌کننده**:

```
                    ┌─────────────────────────────────┐
                    │     NexusPanel (FastAPI :8000)  │
                    │  dashboard · jobs · Xray stdin  │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
   وجه ۱ — عمومی (AGPL)                       وجه ۲ — SigmaGuard (اختصاصی)
   اپراتور / ریسلر                            اپ premium ما
   v2rayNG · Hiddify · WG · AmneziaWG          Flutter + Rust core
   مسیر: /sub/{token}/                         مسیر: /api/v2/client/*
              │                                           │
              ▼                                           ▼
         نودها: Xray · WG/AWG · sing-box (H2/TUIC/AnyTLS) · تونل relay→exit
```

**قانون طلایی:** هر چیزی که Client API سرو می‌دهد از همان subscription لایه ۱ هم قابل ساخت است. اپراتور عمومی هرگز به SigmaGuard نیاز ندارد؛ SigmaGuard لایهٔ افزایشی است.

**تکنولوژی‌ها:** Python 3.12 · FastAPI · SQLAlchemy + Alembic · APScheduler · Xray-core (subprocess + gRPC) · sing-box · WireGuard/AmneziaWG (native روی نود) · RPyC/REST برای نود · Next.js 14 (static export) برای داشبورد.

---

## 2. Bootstrap و چرخه اجرا

### `main.py`
نقطه ورود Uvicorn؛ خود اپ را تعریف نمی‌کند بلکه `app` را از `app/__init__.py` import می‌کند.
- اعتبارسنجی TLS اگر `UVICORN_SSL_*` ست شده باشد.
- bind از طریق UDS (`UVICORN_UDS`) یا TCP (`UVICORN_HOST`/`UVICORN_PORT`).
- `uvicorn.run("main:app", workers=1, reload=DEBUG)` — **چندworker پشتیبانی نمی‌شود** (APScheduler + Xray).

### `app/__init__.py`
```python
app = FastAPI(title="NexusPanel API", version=__version__,
              docs_url="/docs" if DOCS else None, ...)
```
- اشیای سراسری: `scheduler` (`BackgroundScheduler`، UTC، `max_instances=20`)، `logger`، `panel_version()`، `PRODUCT_NAME="NexusPanel"`.

**Middleware (به ترتیب):**
| Middleware | فایل | کار |
|---|---|---|
| `CORSMiddleware` | `app/__init__.py` | فقط اگر `ALLOWED_ORIGINS` غیرخالی؛ با `*` کردنشال غیرفعال |
| `RequestContextMiddleware` | `app/utils/logging.py` | context ساختاریافته request |
| `hide_default_dashboard_middleware` | `app/middleware/dashboard_path.py` | 404 برای `/dashboard/*` وقتی `DASHBOARD_PATH` سفارشی است |
| `security_headers_middleware` | `app/__init__.py` | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS روی HTTPS |

**چرخه عمر:**
- **startup:** structured logging · OpenTelemetry (`app/tracing`) · اعتبارسنجی مسیر subscription · HA leader election (`app/ha.start()`) · backfill tenantهای reseller · sync `install-meta.json` · `scheduler.start()`.
- **shutdown:** `scheduler.shutdown()` · `app/ha.stop()`.

**Exception handlerها:** `RequestValidationError` → 422 با `detail` دیکشنری؛ `StarletteHTTPException` → JSON برای `/api*` یا قالب HTML 404.

**Static mountها (داشبورد):** `{DASHBOARD_PATH}` (پیش‌فرض `/dashboard/`) → `app/dashboard-next/out/dashboard`؛ همچنین `/subscribe`, `/portal`, `/_next`, `/fonts`, `/sub-assets`.

---

## 3. مدل احراز هویت، RBAC و API Key

### انواع توکن (`app/utils/jwt.py`)
| claim `access` | کاربرد |
|---|---|
| `sudo` / `admin` | API پنل ادمین (`OAuth2PasswordBearer` در `/api/admin/token`) |
| `portal` | پورتال کاربر (`/api/portal/*`) |
| `app` | access token کلاینت SigmaGuard |
| `app_refresh` | refresh کلاینت (انقضای ۳۰ روز) |
| `subscription` | لینک ساب به‌صورت JWT (اختیاری) |

توکن subscription می‌تواند **base64 امضاشده** هم باشد: `username,timestamp` + امضای HMAC. اگر `issued_at=None` → timestamp صفر = **توکن پایدار per-user** که بین callها نمی‌چرخد؛ بعد از revoke با `revoked_ts+1` دوباره key می‌شود.

**منابع sudo:** env `SUDO_USERNAME` + `SUDO_PASSWORD_HASH` (ترجیحی) یا legacy `SUDO_PASSWORD`؛ یا ادمین‌های DB با `is_sudo=True`.

### RBAC (`app/rbac.py`)
**Permissionها:** `users:read/write`, `nodes:read/write/provision`, `billing:read/write`, `system:read`, `admins:write`

| نقش | دسترسی‌ها |
|---|---|
| `sudo` (`is_sudo=True`) | همه (ضمنی) |
| `reseller` (پیش‌فرض non-sudo) | users R/W · nodes read+provision · billing R/W · system read |
| `support` | users read · nodes read · system read |

`require_permission(permission)` یک dependency factory است.

### API Keys (`app/api_keys.py`)
- فرمت کلید: `nxp_{prefix}_{secret}`؛ فقط هش SHA-256 ذخیره می‌شود.
- scope matching: scope دقیق، `resource:*`، یا `*`.
- `get_v2_admin` هم `X-API-Key` می‌پذیرد هم bearer JWT ادمین.
- `require_v2_scope(scope)`: روی API keyها enforce می‌شود؛ توکن ادمین bearer از scope check رد می‌شود.

### Dependencyهای کلیدی (`app/dependencies.py`)
`validate_admin` · `get_dbnode` / `get_scoped_node` (با چک مالکیت tenant) · `get_validated_sub(token)` · `get_validated_user(username)` · `get_expired_users_list`.

---

## 4. Routerها و API کامل

Aggregator: `app/routers/__init__.py` که `api_router` را می‌سازد و **۳۵ زیرrouter** را include می‌کند. اکثر APIهای ادمین prefix `/api` دارند؛ subscription از `/{XRAY_SUBSCRIPTION_PATH}` (پیش‌فرض `/sub`).

### احراز هویت و ادمین — `admin.py`, `api_keys.py`
| متد | مسیر | دسترسی |
|---|---|---|
| POST | `/api/admin/token` | عمومی (rate-limited) → JWT |
| POST/PUT/DELETE | `/api/admin[/{username}]` | Sudo |
| GET | `/api/admin` | bearer ادمین |
| GET | `/api/admins` | Sudo |
| POST | `/api/admin/{username}/users/{disable,activate}` | Sudo |
| POST/GET | `/api/admin/usage[/reset]/{username}` | Sudo |
| GET/POST/DELETE | `/api/api-keys[/{key_id}]` | bearer ادمین (کلید خام یک‌بار) |

### کاربران — `user.py`, `user_template.py`, `user_import.py`
| متد | مسیر | permission |
|---|---|---|
| POST | `/api/user` · `/api/user/from-template` | `users:write` |
| GET/PUT/DELETE | `/api/user/{username}` | read/write |
| POST | `/api/user/{username}/reset` · `/revoke_sub` · `/apply-plan` · `/active-next` | `users:write` |
| GET | `/api/users` · `/api/users/usage` · `/api/user/{username}/usage` | `users:read` |
| POST | `/api/users/reset` | Sudo |
| PUT | `/api/user/{username}/set-owner` | Sudo |
| GET/DELETE | `/api/users/expired` | read/write |
| CRUD | `/api/user_template[/{id}]` | Sudo (نوشتن) / read |
| POST/GET | `/api/users/import/{preview,inbounds,formats,apply,apply-file}` | read/write |

### نودها و provisioning — `node.py`, `provisioning.py`, `services.py`, `protocols.py`, `routing.py`, `tunnel.py`
| متد | مسیر | دسترسی |
|---|---|---|
| POST | `/api/node/bootstrap` | **عمومی** (`NODE_BOOTSTRAP_TOKEN`، rate-limited) |
| GET/POST/DELETE | `/api/node/groups[/{id}]` | Sudo |
| POST/GET/PUT/DELETE | `/api/node[/{id}]` | Sudo |
| WS | `/api/node/{id}/logs` | bearer |
| PUT/POST | `/api/node/{id}/singbox[/sync]` · `/singbox/tls/{status,issue,renew,refresh}` | Sudo |
| GET/PUT | `/api/node/{id}/amneziawg[/status]` · `/wireguard/stack` · `/sigmaguard-wire` | Sudo |
| POST | `/api/node/{id}/reconnect` · DELETE node | `nodes:provision` |
| GET | `/api/nodes` (tenant-scoped) · `/api/nodes/usage` | `nodes:read` / Sudo |
| GET/POST | `/api/nodes/{agent-bundle,provision,install-command}` · `/provision/jobs/{id}` | `nodes:provision` |
| GET/PUT | `/api/services` · `/api/node/{id}/services` | Sudo |
| GET | `/api/protocols` | bearer ادمین |
| GET | `/api/routing/{strategies,nodes}` | bearer (flag `smart_routing`) |
| CRUD/POST | `/api/tunnels[/{id}]` · `/{id}/config` · `/{id}/apply` | bearer (flag `tunneling`) |

### Subscription (عمومی، token-based) — `subscription.py`
prefix `/sub` (پیش‌فرض):
| مسیر | خروجی |
|---|---|
| `GET /sub/{token}[/]` | auto-detect از User-Agent |
| `GET /sub/{token}/info` · `/usage` | متادیتا/مصرف |
| `GET /sub/{token}/wireguard[/prepare][/{node_id}]` | `.conf` WG/AWG (`variant=plain\|awg`) |
| `GET /sub/{token}/{hysteria2,tuic,anytls}[/{node_id}]` | لینک QUIC/AnyTLS |
| `GET /sub/{token}/{client_type}` | `sing-box`/`clash-meta`/`clash`/`outline`/`v2ray`/`v2ray-json` |

### سیستم و هسته — `system.py`, `panel_system.py`, `core.py`, `metrics.py`, `backup.py`, `setup.py`, `feature_flags.py`, `platform_settings.py`, `plugins.py`
| متد | مسیر | دسترسی |
|---|---|---|
| GET | `/api/system` · `/api/inbounds` | bearer ادمین |
| GET/PUT | `/api/hosts` | Sudo |
| POST | `/api/system/jwt/rotate` | Sudo |
| GET | `/api/system/version` | **عمومی** |
| GET/POST | `/api/system/deployment` · `/updates/{check,apply}` · `/updates/jobs/{id}` | Sudo |
| GET/POST | `/api/xray/releases` · `/api/system/xray/upgrade` · `/api/nodes/{id}/xray/version` | Sudo |
| GET/POST/PUT | `/api/core[/restart,/config]` · `/core/wireguard/keypair` · `/core/warp[...]` · `/core/outbounds/test` | Sudo |
| WS | `/api/core/logs` | bearer |
| GET | `/api/metrics` | `METRICS_TOKEN` یا sudo (flag `prometheus_metrics`) |
| POST/GET | `/api/backup` · `/api/backups` · `/api/backups/{file}/restore` | Sudo |
| GET/POST | `/api/setup/status` (عمومی) · `/api/setup/` (Sudo) | wizard اولیه |
| GET/PUT | `/api/feature-flags[/{name}]` | Sudo |
| GET/PUT | `/api/platform-settings` | Sudo |
| GET | `/api/plugins` | Sudo |

### Client API v2 و v2 — `client_v2.py` (flag `client_api`), `v2.py` (flag `api_v2`)
| متد | مسیر | دسترسی |
|---|---|---|
| POST | `/api/v2/auth/login` · `/auth/refresh` | عمومی / refresh token |
| GET | `/api/v2/client/negotiate` · `/config` · `/dedicated-ip` | app token |
| POST | `/api/v2/client/probe` · `/telemetry` · `/device-token` (+DELETE) | app token |
| GET | `/api/v2/users` | `X-API-Key`/bearer (scope `users:read`) |

### تجاری — `billing.py` (flag `billing`), `plans.py`, `portal.py` (flag `user_portal`), `reseller.py`, `tenant.py`, `analytics.py`, `intelligence.py`, `dedicated_ip.py`, `rules.py`, `workflows.py`, `marketplace.py`
- **Billing:** `/api/billing/{providers,payment-providers,wallet,credit,invoices,transactions,topup,mrr,usage}` + `webhook/stripe` (عمومی).
- **Plans:** CRUD `/api/plans[/{id}]`.
- **Portal:** `/api/portal/{token,me,plans,renew,payment-providers,payments,branding,orders}`.
- **Reseller:** `/api/reseller/{workspace,sub-accounts,onboarding[/complete]}`.
- **Tenant:** `/api/tenants[/{id}]` (Sudo) · `/api/branding[/mine]` (flag `tenants`/`white_label`).
- **Analytics:** `/api/analytics/{top-users,nodes-usage}`.
- **Intelligence:** `/api/intelligence/{heavy-users,exhaustion-risk,node-risk,summary}` (flag `traffic_intelligence`).
- **Dedicated IP:** `/api/dedicated-ip[/assign,/release]` (Sudo).
- **Rules/Workflows/Marketplace:** CRUD (flagهای `rule_engine`/`workflows`/`plugin_marketplace`).

### Home — `home.py`
`GET /` → رندر `HOME_PAGE_TEMPLATE`.

---

## 5. مدل داده (دیتابیس)

### Setup (`app/db/`)
- `base.py`: engine از `SQLALCHEMY_DATABASE_URL`؛ SQLite (بدون pool) vs PostgreSQL/MySQL (pool + pre_ping)؛ CITEXT برای username غیرحساس به حروف.
- `__init__.py`: `GetDB` context manager · `get_db()` dependency.
- `crud.py`: ~۸۰ تابع (users, admins, templates, nodes, plans, portal, hosts/inbounds, system usage, jwt/tls).

### ORM (`app/db/models.py`) — ~۴۰ جدول
| جدول | فیلدهای کلیدی |
|---|---|
| `admins` | username, hashed_password, is_sudo, role, quotaها (max_users/traffic/nodes), tenant_id, parent_admin_id, commission_percent, telegram_id, users_usage |
| `users` | username (CI), status, used_traffic, data_limit, reset_strategy, expire, admin_id, sub_revoked_at, portal_enabled, hashed_portal_password, client_profile, on_hold_*, auto_delete_in_days, next_plan |
| `next_plans` | user_id, data_limit, expire, add_remaining_traffic, fire_on_either |
| `proxies` | user_id, type (enum), settings (JSON), excluded inbounds (M2M) |
| `inbounds` / `hosts` | tag / remark, address, port, path, sni, security, alpn, fingerprint, mux, fragment, noise |
| `nodes` | name, address, ports, core_kind, status, usage, region, capacity, latency_ms, group_id, tenant/owner, role, provisioning |
| `node_wireguard` | WG + AmneziaWG + SigmaGuard Wire (۱:۱ با node) |
| `node_singbox` | Hysteria2/TUIC/AnyTLS + TLS LE metadata |
| `panel_services` / `node_service_bindings` | کاتالوگ سرویس و فعال‌سازی per-node |
| `node_user_usages` / `node_usages` | aggregate ساعتی مصرف |
| `system` / `jwt` / `tls` | uplink/downlink / کلید امضا / TLS پنل |
| `feature_flags` | name, enabled, admin_id (override) |
| `rules` / `workflows` | اتوماسیون |
| `marketplace_plugins` / `plugin_reviews` | کاتالوگ پلاگین + امتیاز |
| `plans` / `wallets` / `transactions` / `user_orders` / `invoices` / `payment_intents` / `usage_billing_checkpoints` | تجاری |
| `client_probes` / `client_devices` / `client_telemetry` | تله‌متری SigmaGuard |
| `dedicated_ips` | IP ثابت برای trader |
| `tenants` / `branding_settings` | white-label |
| `tunnels` | تعریف relay↔exit |
| `events` / `notification_reminders` / `admin_usage_logs` / `user_usage_logs` | audit/یادآوری/لاگ مصرف |
| `api_keys` | کلید v2 هش‌شده + scopes |

association: `exclude_inbounds_association`, `template_inbounds_association`.

### Alembic — **۹۳–۹۴ migration**
config در `alembic.ini` → `app/db/migrations`. تم‌های اصلی تکامل اسکیما: identity اولیه → hosts/proxy → on-hold/status → node clustering → WireGuard/sing-box/AmneziaWG/AnyTLS/sg_wire → commercial phase 3 → Client API → feature flags/events → white-label/tunnels phase 6 → user portal → panel services → CITEXT/PostgreSQL.

---

## 6. پروتکل‌ها و موتورها

### `app/xray/` — مدیریت Xray
| فایل | نقش |
|---|---|
| `core.py` | `XRayCore` — `xray run -config stdin:`؛ ring buffer لاگ؛ tunnel inject در start |
| `config.py` | `XRayConfig` — parse/validate؛ inject API inbound (dokodemo)؛ `_resolve_inbounds()` متادیتای محصول؛ `include_db_users()` |
| `serving.py` | hot-sync کاربر با gRPC HandlerService (بدون restart کامل) |
| `operations.py` | connect/restart نود؛ push کاربر؛ debounce |
| `node.py` | `ReSTXRayNode`, `RPyCXRayNode` (mTLS) |

**پروتکل‌های Xray:** VMess · VLESS (+XTLS flow) · Trojan · Shadowsocks (legacy + **SS-2022**: blake3-aes-128/256-gcm, chacha20) · WireGuard (فقط AmneziaWG-marked به‌عنوان product inbound) · **Reality** (حالت TLS روی VLESS/Trojan).
**Transportها:** tcp/raw · ws · grpc/gun · quic · httpupgrade · splithttp/xhttp · kcp · http/h2/h3. **Security:** none/tls/reality.
**نکته hot-sync:** SS-2022 از hot-sync مستثناست (gRPC AddUser هسته را crash می‌کند) → نیاز reload کامل config.

### `app/wireguard/` — WG و AmneziaWG (dual-stack)
WireGuard native روی **نود** اجرا می‌شود (نه gRPC Xray)؛ پنل spec اعلانی می‌سازد، نود با `wg`/`awg syncconf` اعمال می‌کند.
| Variant | interface | پورت پیش‌فرض | subnet |
|---|---|---|---|
| Plain WG | `wg0` | **51820** | `10.10.0.0/24` |
| AmneziaWG | `wg1` | **51821** | `10.11.0.0/24` |

پارامترهای obfuscation AWG: `Jc/Jmin/Jmax`, `S1–S4`, `H1–H4` (+ کلاینت-only `I1–I5`). MTU توصیه‌شده **1280**. فقط peerهای `active` push می‌شوند.

### `app/singbox/` — Hysteria2 / TUIC / AnyTLS
| پروتکل | flag | پورت | transport |
|---|---|---|---|
| Hysteria2 | `hysteria2_enabled` | `hysteria2_port` | **QUIC** (+ salamander obfs) |
| TUIC | `tuic_enabled` | `tuic_port` | **QUIC** (ALPN h3) |
| AnyTLS | `anytls_enabled` | `anytls_port` | **TCP/TLS** |

tag کاربر: `{user_id}.{username}`. آمار از طریق **Clash API** نود روی `127.0.0.1:{clash_api_port}` (پیش‌فرض **9095**).

### `app/protocols/` — registry بک‌اند
`XrayBackend` (vmess/vless/trojan/ss) · `SingBoxBackend` (h2/tuic/anytls) · `Hysteria2Backend` · `TuicBackend` · `AnyTLSBackend`. توسط Client API برای تبلیغ فقط پروتکل‌های قابل‌تحویل استفاده می‌شود.

---

## 7. Subscription و فرمت‌های کلاینت

### ماژول‌ها (`app/subscription/`)
`share.py` (ارکستریتور) · `v2ray.py` · `clash.py` · `singbox.py` · `outline.py` (فقط SS) · `quic.py` · `wireguard.py` · `guards.py` · `public_url.py`.

### فرمت‌ها (`generate_subscription`)
| `config_format` | خروجی | base64 |
|---|---|---|
| `v2ray` | لینک per inbound/host | اختیاری (پیش‌فرض true) |
| `clash` / `clash-meta` | YAML | خیر |
| `sing-box` | JSON outbounds | خیر |
| `outline` | JSON Shadowsocks | خیر |
| `v2ray-json` | کانفیگ کامل V2Ray | خیر |

### auto-detect از User-Agent
Clash Verge/Meta/Mihomo → `clash-meta` · Clash/Stash → `clash` · SFA/SFI/Karing/HiddifyNext → `sing-box` · SS/Outline → `outline` · v2rayN ≥6.40 / v2rayNG ≥1.8.29 / HiddifyNextX → `v2ray-json` · پیش‌فرض → `v2ray` base64.

### لینک QUIC (`quic.py`)
- **Hysteria2:** `hysteria2://{pw}@{host}:{port}?insecure=1&sni=...&obfs=salamander&obfs-password=...`
- **TUIC:** `tuic://{uuid}:{pw}@{host}:{port}?congestion_control=bbr&udp_relay_mode=native&alpn=h3&insecure=1`
- **AnyTLS:** `anytls://{pw}@{host}:{port}?insecure=1&sni=...`

**Gating (`guards.py`):** 403 برای کاربر disabled/limited/expired/over-quota؛ HTML `/info` همیشه خواندنی.

---

## 8. Client API v2 و SigmaGuard

### Router `client_v2.py` (prefix `/api/v2`, flag `client_api`)
login/refresh → JWT app؛ negotiate → پروتکل‌های قابل‌استفاده مرتب؛ config → پروتکل + node picks + `protocol_materials` + sub URL؛ probe → ذخیره ping + بهترین نود؛ telemetry/device-token؛ dedicated-ip (trader).

### منطق negotiate (`app/client/__init__.py`)
**پروفایل‌ها:** `gamer` / `trader` / `normal`
**کاتالوگ:** sigmaguard-wire, amneziawg, hysteria2, tuic, vless-reality, shadowsocks-2022, wireguard, cdn
**UDP-required:** sigmaguard-wire, amneziawg, hysteria2, tuic, wireguard
**Camouflaged:** vless-reality, cdn, anytls

| پروفایل | اولویت |
|---|---|
| gamer | sigmaguard-wire → amneziawg → hysteria2 → vless-reality (auto-switch) |
| trader | فقط vless-reality (نود pinned، بدون failover) |
| normal | vless-reality → shadowsocks-2022 → cdn |

شبکه `heavily_restricted` همه غیر-camouflaged را block می‌کند. `select_nodes()` بر اساس probe ping + packet loss + region hint رتبه می‌دهد.

### Materials (`app/client/materials.py`)
| کلید | payload |
|---|---|
| wireguard / amneziawg | `{node_id, node_name, conf}` |
| sigmaguard-wire | `{conf, preset_rev, engine, node_id}` |
| hysteria2 / tuic / anytls | `{node_id, node_name, link, tls_trusted}` |
| vless-reality / shadowsocks-2022 / cdn | `{outbounds: [...]}` |

auto-provision (`provision.py`): برای کاربران پورتال VLESS/WG/Hysteria2 (+SS-2022 با flag) می‌سازد.

### SigmaGuard Wire (`app/sigmaguard_wire/bridge.py`)
- **فقط Client API** — نه `/sub/` عمومی.
- preset از `SIGMAGUARD_WIRE_ROOT` (پیش‌فرض auto-detect `/opt/sigmaguard/wire/presets/sigma_preset.py`).
- flag `sigmaguard_wire` + نیاز AWG + `sg_wire_enabled` روی نود.
- `build_client_conf()` → AWG conf با پارامترهای سرور + کلیدهای کلاینت-only؛ **`I1` برای AmneziaVPN iOS حذف می‌شود** (interop).

> جزئیات کامل اکوسیستم SigmaGuard در `/opt/SIGMAGUARD_HANDOFF.md`.

---

## 9. معماری نود (Node Agent)

نود در `/opt/nexuspanel/node/` است. `SERVICE_PROTOCOL=rpyc|rest`، پورت پیش‌فرض **62050** (Xray API نود **62051**).

### RPyC service (`node/rpyc_service.py` — `XrayService`)
متدهای `@rpyc.exposed`:
- **Xray:** `start/stop/restart(config)` · `fetch_xray_version` · `upgrade_xray(tag)` · `fetch_logs(callback)`
- **WireGuard:** `wg_apply[_json/_specs_json]` · `wg_transfer` · `wg_down` · `wg_amnezia_available` · `wg_recover_awg_interface` · `wg_reconcile_awg_endpoints(interface, stale_sec)` · `wg_flush_bad_endpoints` · `wg_prepare_peer_for_connect(interface, pubkey)` · `wg_flush_stale_peers`
- **sing-box:** `singbox_apply_json` · `singbox_transfer` · `singbox_available` · `singbox_down` · `singbox_tls_status`

**سیاست اتصال:** تک‌اتصال پنل؛ اتصال جدید رد می‌شود اگر peer قبلی زنده باشد.

### REST (`node/rest_service.py`)
WG: `/wg/{apply,apply-specs,transfer,down,amnezia-available}` · sing-box: `/singbox/{apply,transfer,down,tls-status}`.

> باگ‌های ریشه‌ای AWG (reconnect/endpoint مرده/PSK/recover loop) در جلسات قبل رفع شدند — رجوع به `/opt/SIGMAGUARD_HANDOFF.md`.

---

## 10. تونل relay→exit (ایران)

`app/tunnel/` — `__init__.py` (builderها) + `inject.py` (`apply_endpoint_tunnels`).

```
client → relay (ایران، node یا پنل) → exit (خارج) → اینترنت
```

**transportهای پشتیبانی‌شده:** `reality`, `ws`, `grpc`, `tcp`.
builderها: `build_relay_outbound` · `build_relay_routing_rule` · `build_exit_inbound` · `build_wireguard_relay_inbound` (dokodemo-door UDP capture → WG داخل Reality).
inject از `XRayCore.start()` (پنل، `node_id=None`) و `connect_node()` (per node) فراخوانی می‌شود.
پارامتر پیش‌فرض Reality: `flow=xtls-rprx-vision`, `sni=www.cloudflare.com`, کلید x25519 خودکار. نقش نود: `direct`/`relay`/`exit`.

---

## 11. داشبورد (Frontend)

**مسیر:** `app/dashboard-next` · **package `0.12.0`** · سرو در `https://<host>/dashboard/` (هش روت).

### استک
Next.js **14.2.18** (static export `output: "export"`) · React 18.3 · **react-router-dom** (HashRouter داخل `/dashboard/`) · i18next · Tailwind (صفحات عمومی) + CSS سفارشی `design-pro.css` (پنل) · فونت Vazirmatn + Inter. build: `./build_dashboard.sh` با `NEXT_PUBLIC_BASE_API=/api/`.

### الگوی معماری
Next.js چهار shell ثابت می‌دهد (`/`, `/dashboard/`, `/subscribe/`, `/portal/`)؛ پنل ادمین یک **SPA client-only** با HashRouter است (`/dashboard/#/users`).

### ناوبری: ۵ منو + ۳ هاب
**Sudo:** Home (`#/overview`) · Users · **Servers** (هاب) · **Protocols & links** (هاب `#/connection`) · **Business** (هاب) · footer: Copilot + System.
**reseller:** home/users/servers/business · **support:** home/users/business (بدون servers).

### هاب‌ها (با `?tab=`)
- **Servers:** nodes · services (sudo) · wireguard (sudo) · h2 [Hysteria2/TUIC/AnyTLS] (sudo) · tunnels (flag `tunneling`) · dedip (flag `client_api`).
- **Connection:** inbounds · outbounds · routing · hosts · advanced [DNS/JSON] (expert mode).
- **Business:** billing (flag) · resellers · analytics · automation (sudo) · commercial.

### ۲۱ صفحه (`src/panel/pages/`)
Login · Overview · Users · ServersHub · ConnectionHub · BusinessHub · System · Nodes · Infrastructure · WireGuard · SingBox · ServicesManager · TunnelsPage · DedicatedIP · Inbounds · Hosts · XrayConfig · Billing · Resellers · Analytics · Automation.

### امکانات کلیدی UI
- **ویزارد ۳ مرحله ساخت کاربر** (Identity → Connection [کارت پروتکل] → Limits)؛ expert mode آن را bypass می‌کند.
- **Expert mode** (System → About؛ `localStorage nx_expert_mode`) → تب Advanced در Connection.
- **Inbound editor** (`components/xray/InboundEditor.tsx`): protocol picker، Reality keygen، fallbacks، sniffing؛ save با `PUT /core/config` + `xray run -test`.
- **Setup wizard** اولیه (sudo) · **Reseller onboarding** · **Copilot** (راهنمای deep-link).
- gating با feature flag و نقش (support read-only، SudoGate).

### i18n
en (مرجع، کامل) · fa (parity کامل) · ru/zh (~۸۳٪، بخش‌های hub/outbounds/warp/services ناقص → fallback انگلیسی). subscribe/portal i18n جدا دارند.

### اتصال به API
`src/panel/api/client.ts`: base `/api/`؛ `Authorization: Bearer`؛ توکن در `localStorage nx_token`؛ login `POST /admin/token`؛ 401 → logout. پورتال: `nx_portal_token` و `POST /portal/token`.

### legacy
`app/dashboard/__init__.py` فقط لایه FastAPI برای سرو static export است — **dashboard-next تنها frontend است**، رقیب قدیمی وجود ندارد.

---

## 12. Jobها (کارهای پس‌زمینه)

auto-load از `app/jobs/__init__.py` (همه `*.py` غیر از `_`-prefixed). اکثر job singleton از `run_if_leader` (نیاز Redis برای HA).

| فایل | بازه پیش‌فرض | کار |
|---|---|---|
| `0_xray_core.py` | startup + ~۱۰ث health / ~۴۵ث reconcile | start هسته + connect نودها؛ health probe؛ restart نود crashed (cooldown 60s)؛ AWG endpoint reconcile؛ WG resync |
| `record_usages.py` | ۱۰ث user / ۳۰ث node | کشیدن آمار Xray/WG/sing-box؛ `NodeUserUsage`/`NodeUsage`؛ quota clamp |
| `review_users.py` | ۱۰ث | expire/limit؛ apply `next_plan`؛ on-hold→active؛ یادآوری webhook |
| `reset_user_data_usage.py` | ۱ ساعت | reset مصرف day/week/month/year |
| `remove_expired_users.py` | ۶ ساعت | auto-delete منقضی‌ها |
| `send_notifications.py` | ۳۰ث (اگر `WEBHOOK_ADDRESS`) | drain صف + POST با HMAC-SHA256 |
| `backup.py` | هر N ساعت (`BACKUP_INTERVAL_HOURS`، پیش‌فرض 0=خاموش) | `create_backup()` |
| `bill_usage.py` | ساعتی (اگر rate>0) | مترینگ GB با تخفیف BYO-node |
| `intelligence.py` | `INTELLIGENCE_SCAN_INTERVAL` (0=خاموش) | heavy users/exhaustion/node risk (flag) |
| `cluster.py` | `CLUSTER_FAILOVER_CHECK_INTERVAL` (0=خاموش) | `detect_failures()` |
| `event_bus.py` | ۶ ساعت | prune eventها (`EVENTS_RETENTION_DAYS`) + persist بس |
| `tls_expiry.py` | cron 04:15 | هشدار انقضای cert LE sing-box (≤۷ روز) |
| `automation.py` | startup hook | load پلاگین/rule/workflow |

---

## 13. ماژول‌های تجاری

### `app/billing/`
wallet/transaction (واحد minor صحیح) · invoice · `pay_invoice` · `usage_billing.py` (متر GB، split نود owned/foreign، checkpoint) · `payments.py` (top-up ادمین + پرداخت مستقیم پورتال) · `providers.py` (manual/demo/stripe stub) · `commission.py` (کمیسیون reseller والد) · `mrr.py`.

### `app/marketplace/`
کاتالوگ پلاگین DB-backed؛ seed: `event_log`, `node_alert`, `auto_heal`؛ install/uninstall + review/rating. کد remote اجرا نمی‌کند.

### `app/portal/`
self-service کاربر نهایی: `apply_plan_to_user` · `create_user_order`/`mark_order_applied` + integration با payments.

### `app/tenant/`
CRUD tenant + slugify + scoping ادمین + branding (per-tenant با fallback سراسری) · `reseller_ops.py` (quota، KPI، مالکیت نود) · `plan_ops.py` · `sub_reseller.py` (سلسله‌مراتب sub-reseller، کمیسیون موروثی).

### `app/intelligence/`
`run_scan()`: heavy users (median-based) · پیش‌بینی exhaustion پهنای‌باند · node risk؛ `detectors.py` heuristic خالص. flag `traffic_intelligence`.

---

## 14. زیرساخت داخلی

- **`app/middleware/dashboard_path.py`** — مخفی‌سازی `/dashboard/` پیش‌فرض وقتی مسیر سفارشی.
- **`app/services/`** — کاتالوگ سرویس: `catalog.py` (SERVICE_SEEDS: xray, wireguard-plain, amneziawg, hysteria2, tuic...) · `materialize.py` · `node_apply.py` · `node_pick.py` · `xray_node.py` · `hosts_sync.py`.
- **`app/events/`** — `bus.py` (pub/sub درون‌فرایندی) · `types.py` (EventType) · `redis_backend.py` (Redis Streams برای HA) · bridge به notificationها.
- **`app/workflows/`** — توالی چندمرحله‌ای event-triggered (flag `workflows`).
- **`app/rules/`** — موتور قانون: match event → condition → action (flag `rule_engine`).
- **`app/plugins/`** — `base.py` + `builtin.py` (EventLog, NodeAlert, AutoHeal با cooldown 60s)؛ flagهای `plugins`/`auto_healing`.

---

## 15. امنیت

- **`SECURITY.md`** — سیاست گزارش آسیب‌پذیری؛ `.env` در gitignore؛ چک‌لیست production.
- **`app/tls/`** — `inspect.py` (تشخیص CA عمومی، `cert_requires_insecure`) · `self_signed.py` · `acme.py` (LE نود از طریق SSH، domain یا IP). TLS لبه = nginx (نه uvicorn).
- **mTLS نود↔پنل** — `scripts/generate_node_mtls.sh` → `/var/lib/nexuspanel/certs/mtls/{ca,client}.pem`؛ نود `SSL_CLIENT_CERT_FILE`؛ پنل `NODE_SSL_VERIFY=True` (نیاز deploy `ca.pem` روی نود).
- **`app/backup.py`** — `.tar.gz` در `BACKUP_DIR` (mode 700)؛ DB dump (sqlite/pg_dump/mysqldump) + TLS + xray_config + اختیاری `.env`؛ tar-slip protection؛ retention (پیش‌فرض ۷).
- **`app/login_limit.py`** — ۱۰ تلاش / ۹۰۰ث per IP → 429.
- **`app/bootstrap_limit.py`** — ۲۰ تلاش / ۳۶۰۰ث per IP → 429.
- **`app/quota.py`** — `clamp_usage_delta` (cap سخت) · `limit_user_quota` (active→limited + حذف peer/inbound زنده).

---

## 16. Deployment و Ops

### سه حالت deploy
| حالت | compose | DB | Redis | TLS |
|---|---|---|---|---|
| Docker مینیمال | `docker-compose.yml` | SQLite | اختیاری | nginx + LE |
| Production | `docker-compose.postgres.yml` | PostgreSQL 16 | Redis 7 (AOF) | nginx + LE |
| بدون Docker | `install_service.sh` + `run_local.sh` | SQLite/PG | اختیاری | `setup_https.sh` |

- **Dockerfile:** multi-stage `python:3.12-slim`؛ دانلود Xray-core (arch-aware)؛ نیاز داشبورد pre-built؛ user `nexuspanel` (uid 1000)؛ ENTRYPOINT `docker-entrypoint.sh` CMD `panel`.
- **`docker-compose.yml`:** سرویس `nexuspanel`، `network_mode: host`، volumeها: `/var/lib/nexuspanel`, `.:/code`, `/opt/sigmaguard/wire:ro`, docker.sock.
- **`docker-compose.postgres.yml`:** + postgres:16-alpine + redis:7-alpine (همه host networking، healthcheck).
- **`docker-entrypoint.sh`:** root → fix permission → `runuser nexuspanel` → `alembic upgrade head && python main.py`.
- **nginx:** روی host، TLS روی `:443` → `127.0.0.1:8000`؛ از `setup_https.sh` (domain LE یا IP short-lived cert با certbot ≥5.4).
- **HA / event bus:** نیاز Redis برای leader election چندپنلی.

---

## 17. اسکریپت‌ها

**اصلی:**
- `scripts/nexuspanel.sh` — **نصب‌کننده و مدیر اصلی** (install/update/up/down/restart/status/logs/backup/restore/cli/uninstall/https/doctor)؛ نصب به `/usr/local/bin/nexuspanel`؛ پیش‌فرض Docker postgres + HTTPS.
- `scripts/setup_env.sh` — تولید `.env` با اسرار تصادفی + bcrypt admin (یک‌بار چاپ).
- `scripts/setup_https.sh` — nginx + LE (domain/IP) + auto-renew + هم‌ترازی URL در `.env`.
- `scripts/deploy_production.sh` — git pull + build dashboard + compose postgres up.
- `scripts/generate_node_mtls.sh` — CA + client cert.
- `scripts/enable_panel_flags.py` — فعال‌سازی flagهای client_api/api_v2/ss2022/cdn/tunneling/push/provisioning/portal.
- `scripts/pg_migrate.py` — مهاجرت SQLite → PostgreSQL.

**E2E/QA:** `wg_e2e.py`, `wg_smoke_test.py` (ip netns ایزوله), `wg_limit_test.py`, `wg_traffic_test.sh`, `wg_node_setup.py`, `wg_rebuild_agent.py`, `ensure_wg_host_egress.py`, `sb_e2e.py`, `sb_smoke_test.py`, `tunnel_e2e.py`, `reality_smoke_test.py`, `ss2022_smoke_test.py`, `check_data_limit.py`, `setup_panel_stack.py`, `enable_sigmaguard_wire.py`.

**installer:** `installer/shell_wizard.sh` (پیش‌فرض 3x-ui style) · `tui_wizard.py` (curses) · `wizard_server.py` (وب روی 8765 با `WEB_WIZARD=1`).

---

## 18. Monitoring

`docker-compose.monitoring.yml` (bridge): **Prometheus** (`:9090`، scrape `host.docker.internal:8000/api/metrics` با Bearer `METRICS_TOKEN`) + **Grafana** (`:3000`).
متریک‌ها: `nexuspanel_online_users`, `nexuspanel_users{status}`, `nexuspanel_node_connected`, `nexuspanel_bandwidth_bytes_total`, `nexuspanel_node_bandwidth_bytes_total`.
فعال‌سازی: `METRICS_TOKEN` در `.env` + flag `prometheus_metrics` + همان token در `monitoring/prometheus.yml`.

---

## 19. تست‌ها

**۵۶ ماژول تست** در `tests/` (+ `conftest.py`). دسته‌ها: phaseها (2–6) · WireGuard/AWG · sing-box/QUIC · Xray core/inbound/ss2022 · SigmaGuard Wire · billing/commercial/portal/reseller · Client API v2 · security/backup/tls/quota/audit · automation (event bus/rules/conditions/plugins/flags) · subscriptions · platform/system polish/update jobs.
اجرا: `cd /opt/nexuspanel && python3 -m pytest -q` (≈۳۰۶ passed در آخرین handoff).

---

## 20. Config کامل و Feature Flagها

### آپشن‌های اصلی `config.py`
- **DB/زیرساخت:** `SQLALCHEMY_DATABASE_URL`, `SQLALCHEMY_POOL_SIZE` (10), `SQLALCHEMY_MAX_OVERFLOW` (30), `REDIS_URL`, `EVENTS_RETENTION_DAYS` (30), `LOG_JSON`.
- **نود:** `NODE_BOOTSTRAP_TOKEN`, `NODE_CONTROL_SECRET`, `NODE_SSL_VERIFY` (False), `NODE_BOOTSTRAP_MAX_ATTEMPTS` (20), `NODE_BOOTSTRAP_WINDOW_SECONDS` (3600), `NODE_AGENT_IMAGE`, `NODE_DEFAULT_PORT` (62050), `NODE_DEFAULT_API_PORT` (62051), `NODE_PROVISION_*`.
- **امنیت/login:** `LOGIN_MAX_ATTEMPTS` (10), `LOGIN_MAX_WINDOW_SECONDS` (900), `SUDO_USERNAME/PASSWORD/PASSWORD_HASH`, `METRICS_TOKEN`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (1440).
- **cluster/HA:** `CLUSTER_FAILOVER_CHECK_INTERVAL` (0), `CLUSTER_NODE_DOWN_SECONDS` (180), `CLUSTER_AUTO_DISABLE_DOWN_NODES`, `HA_ENABLED`, `HA_INSTANCE_ID`, `HA_LEADER_TTL` (15).
- **routing/intelligence:** `ROUTING_STRATEGY` (latency), `INTELLIGENCE_SCAN_INTERVAL` (0), `INTELLIGENCE_HEAVY_FACTOR` (3.0), `INTELLIGENCE_EXHAUSTION_WINDOW_HOURS` (48), `INTELLIGENCE_NODE_LATENCY_MS` (500).
- **observability:** `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`.
- **panel/شبکه:** `PANEL_REGION`, `PANEL_PUBLIC_ADDRESS`, `UVICORN_HOST/PORT/UDS/SSL_*`, `DASHBOARD_PATH` (/dashboard/), `DEBUG`, `DOCS`, `ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `VITE_BASE_API` (/api/).
- **Xray/sub:** `XRAY_JSON`, `XRAY_EXECUTABLE_PATH`, `XRAY_ASSETS_PATH`, `XRAY_SUBSCRIPTION_URL_PREFIX`, `XRAY_SUBSCRIPTION_PATH` (sub), `XRAY_FALLBACKS_INBOUND_TAG`, `XRAY_EXCLUDE_INBOUND_TAGS`, قالب‌های `*_SUBSCRIPTION/SETTINGS_TEMPLATE`, `WARP_DATA`.
- **backup:** `BACKUP_DIR`, `BACKUP_INTERVAL_HOURS` (0), `BACKUP_RETENTION_COUNT` (7), `BACKUP_INCLUDE_ENV`.
- **notify/telegram/discord/push:** `TELEGRAM_*`, `DISCORD_WEBHOOK_URL`, `FCM_*`, `APNS_*`, `NOTIFY_*`, `NOTIFY_REACHED_USAGE_PERCENT` ([80]), `NOTIFY_DAYS_LEFT` ([3]), `WEBHOOK_ADDRESS/SECRET`, `RECURRENT_NOTIFICATIONS_*`.
- **billing:** `USAGE_BILLING_RATE_PER_GB` (0), `WALLET_LOW_BALANCE_THRESHOLD` (10000), `PAYMENT_DEMO_ENABLED`, `PORTAL_DIRECT_PAYMENT`, `PAYMENT_MIN/MAX_AMOUNT`, `SUB_RESELLER_MAX_PER_PARENT` (10).
- **برند/متفرقه:** `PANEL_DEFAULT_LANG` (en), `PANEL_TITLE`, `PRIMARY_COLOR` (#5b8cff), `USERS_AUTODELETE_DAYS` (-1), `JOB_*_INTERVAL`, `PANEL_GITHUB_REPO/BRANCH`.

### Feature Flagها (`app/feature_flags.py`)
ترتیب resolve: per-admin DB → global DB → پیش‌فرض کد. همه پیش‌فرض **False** مگر `setup_wizard` (**True**).

| flag | کار |
|---|---|
| `prometheus_metrics` | endpoint `/api/metrics` |
| `plugins` / `auto_healing` | سیستم پلاگین / auto-restart نود |
| `rule_engine` / `workflows` | اتوماسیون |
| `billing` / `user_portal` | تجاری / پورتال کاربر |
| `api_v2` / `client_api` | API توسعه / API اپ SigmaGuard |
| `client_ss2022` / `cdn_fallback` / `client_push` | SS-2022 در negotiate / CDN fallback / push |
| `sigmaguard_wire` | پروتکل SigmaGuard Wire |
| `smart_routing` / `traffic_intelligence` | routing هوشمند / تحلیل ترافیک |
| `plugin_marketplace` | مارکت‌پلیس |
| `tenants` / `white_label` | tenant / branding |
| `node_provisioning` / `tunneling` | provisioning SSH / تونل relay→exit |
| `setup_wizard` (True) | ویزارد نصب اولیه |
| `reseller_onboarding_completed` | onboarding reseller |

> `setup_completed` در DB ذخیره می‌شود (خارج از `KNOWN_FLAGS`).

---

## 21. تاریخچه نسخه

از `CHANGELOG.md` (0.9.0 → 0.12.13):
- **0.12.x** — آپدیت Docker از داشبورد، installer HTTPS، رفع AmneziaWG، compose project name، مسیرهای آپدیت هوشمند (restart vs pip vs rebuild).
- **0.11.0** — web installer wizard، مسیر مخفی داشبورد، branding reseller، popup «what's new» محلی.
- **0.10.0** — deploy واقعی تونل (relay/exit Xray)، keygen خودکار Reality، WireGuard-in-Reality، hardening بک‌اند.
- **0.9.x** — semver، ویزارد import کاربر، systemd restart.

> **شکاف:** `CHANGELOG.md` تا 0.12.13 است ولی `VERSION` = **0.13.0** (کار پس از 0.12 / SigmaGuard Wire هنوز log نشده). `docs/PROJECT_STATUS.md` هم روی 0.10.0 مانده (stale).

---

## 22. وضعیت فعلی و کارهای باز

### زیرساخت زنده (این deploy)
| مورد | مقدار |
|---|---|
| پنل | `https://91.220.8.251/` (nginx TLS · :8000 localhost) |
| نود | `wireguard1` · id=1 · `178.83.45.253` (interface `wg1` · `amneziawg-go`) |
| کاربر تست | `alireza` · id=5 |
| DB تولید | `/var/lib/nexuspanel/db.sqlite3` |
| pytest | ~۳۰۶ passed |

### پورت‌ها
| سرویس | پورت | ایران |
|---|---|---|
| VLESS Reality | 8443/TCP | ✅ بهترین TCP |
| VLESS WS | 2095/TCP | خوب پشت CDN |
| WG plain | 51820/UDP | متوسط |
| AmneziaWG / SigmaGuard Wire | 51821/UDP | بهتر از WG خام |
| Hysteria2 | 44333/UDP | اپراتور-وابسته |
| TUIC | 44334/UDP | ❌ عملاً نه |
| نود agent | 62050 (RPyC/REST) · Xray API 62051 | — |

**توصیه ایران:** Reality → H2 → AWG → تونل relay→exit. TUIC به‌عنوان primary پیشنهاد نشود.

### کارهای باز
| ID | موضوع | شدت |
|---|---|---|
| D09 | تونل E2E production ایران↔خارج | بحرانی (ops) |
| G03 | rebuild ایمیج نود (fix zombie sing-box) | بالا |
| G04 | LE روی wireguard1 (نیاز DNS) | متوسط |
| G05 | اپ Flutter SigmaGuard | بالا |
| C06 | ProvisionTab reseller ناقص | متوسط |
| F09 | i18n ru/zh ناقص (~۸۳٪) | متوسط |
| — | endpoint AWG → UDP 443 (مودم) + `transport_modes` در Client API | برنامه‌ریزی‌شده |
| امنیت | mTLS نود (deploy `ca.pem` + flip `NODE_SSL_VERIFY`)؛ rotate SSH نود | P0 باز |
| docs | به‌روزرسانی CHANGELOG/PROJECT_STATUS به 0.13.0 | پایین |

---

## مستندات مرتبط
| فایل | نقش |
|---|---|
| `docs/NEXUSPANEL_FULL_REPORT.md` | **این فایل — گزارش جامع پنل** |
| `docs/CENTRAL-HANDOFF.md` | handoff پنل + مدل دو وجهی + صف امنیتی |
| `docs/CLIENT_API.md` | قرارداد `/api/v2/client/*` |
| `docs/SIGMAGUARD_WIRE.md` | flag و Client API SigmaGuard Wire |
| `docs/PUBLIC_DEPLOYMENT.md` | راهنمای اپراتور عمومی |
| `docs/accounting-contract.md` | قرارداد accounting مصرف یکپارچه |
| `docs/AUDIT-CLOSURE.md` | بستن یافته‌های امنیتی |
| `/opt/SIGMAGUARD_HANDOFF.md` | اکوسیستم SigmaGuard (اپ + wire) |
| `/opt/WORKSPACE.md` | نقشه دو repo |
