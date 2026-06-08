<div align="center">

<img src="https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/docs/logo.svg" width="88" alt="NexusPanel" />

# NexusPanel

**专业代理管理平台 — 多节点、白标、可商用**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC)](tests/)

[English](./README.md) · [فارسی](./README-fa.md) · **简体中文** · [Русский](./README-ru.md)

</div>

---

## 一键安装 (VPS)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
```

面板：`http://IP:8000/dashboard/` · 功能开关：`#/system`

---

## 功能概览

| 层级 | 说明 |
|------|------|
| 核心 | 用户、节点、订阅、Telegram |
| 基础设施 | PostgreSQL、Redis、备份、特性开关 |
| 运维 | Prometheus、Grafana、规则引擎、插件 |
| 商业 | RBAC、套餐、钱包、发票、GB 用量计费、Stripe、API v2 |
| 白标 | 经销商账号、子经销商佣金、租户、品牌、SSH 节点、用户门户 `/portal/` |

**商业设置（UI）**：所有者可在 **System → Commercial** 配置 GB 费率、Stripe 密钥与 webhook、子经销商上限与默认佣金。`.env` 仅作回退。

Stripe webhook：`https://YOUR_PANEL/api/billing/webhook/stripe`

---

## 安全：`tests/` 目录可以放在 GitHub 吗？

**可以，而且建议保留** — 仅为 pytest 自动化测试，无密钥、无生产数据。详见 [SECURITY.md](SECURITY.md)。

---

## 许可证

[AGPL-3.0](LICENSE) · [仓库](https://github.com/KhaJehAmiri/nexuspanel)
