# NexusPanel Dashboard (v2)

The modern NexusPanel control plane UI — built from scratch (no Marzban DNA).

- **Stack:** React 18 + TypeScript + Vite, hand-rolled design system (CSS variables), `react-router-dom` (HashRouter), `i18next`.
- **Languages:** English, فارسی (RTL), Русский, 中文 — switchable at runtime; direction flips automatically.
- **Theme:** dark-first with a light theme toggle.
- **Modules:** Overview, Users, Infrastructure (nodes + tunnels), Resellers & Brand (tenants, branding, SSH provisioning), Automation (rules, workflows, plugins), Analytics (+ traffic intelligence), Billing (plans, invoices, transactions, wallet), System (feature flags, backups, API keys, appearance).

## Develop

```bash
npm install
npm run dev          # http://localhost:3100  (set VITE_BASE_API to your panel /api/)
```

## Build

```bash
npm run build        # outputs to ./build (assets under /statics)
```

The FastAPI app serves `app/dashboard-v2/build` automatically when it exists
(see `app/dashboard/__init__.py`), otherwise it falls back to the legacy
dashboard. Assets are referenced absolutely at `/statics/...` and served by the
panel's `/statics` mount.
