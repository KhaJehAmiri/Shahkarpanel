# HTTPS & reverse proxy

NexusPanel is designed to run **behind nginx with TLS**. The app itself binds to
`127.0.0.1` and is never exposed directly to the internet. One script,
[`scripts/setup_https.sh`](../scripts/setup_https.sh), provisions everything.

## What it does

- Installs nginx (and certbot ≥ 5.4 in a venv when an IP certificate is needed).
- Issues a publicly trusted **Let's Encrypt** certificate:
  - **Domain mode** — standard HTTP-01 certificate (`--domain panel.example.com`).
  - **IP mode** (default) — Let's Encrypt **IP-address certificate** using the
    `shortlived` 6-day profile, for deployments that only have a bare IP.
- Configures the nginx vhost: `:443` TLS → `127.0.0.1:<port>`, `:80` → HTTPS
  redirect (except the ACME challenge path), WebSocket upgrade, HSTS and other
  security headers, 200 MB body limit for backups.
- Sets up **automatic renewal** (`certbot-renew.timer`) with an nginx reload
  hook — important because IP certificates expire every 6 days.
- Updates `.env`: `UVICORN_HOST=127.0.0.1`, `PANEL_PUBLIC_ADDRESS=https://…`,
  and `ALLOWED_ORIGINS`, then restarts the panel (systemd or docker).

## Usage

```bash
# Bare IP (auto-detected public IP), IP-address certificate:
sudo scripts/setup_https.sh

# Or with a domain (recommended when you have one):
sudo scripts/setup_https.sh --domain panel.example.com --email you@example.com

# Re-run any time to rotate/repair; or via the manager:
sudo nexuspanel https            # honours DOMAIN= / EMAIL= env vars
```

The one-line installer (`nexuspanel install`) runs this automatically at the end
of installation. Set `SKIP_HTTPS=1` to opt out (e.g. behind an external LB), or
`DOMAIN=panel.example.com EMAIL=you@example.com` to get a domain certificate.

## Requirements

- Ports **80 and 443** reachable from the internet (80 is required for ACME
  validation; the installer opens them in UFW when UFW is present).
- For domain mode, the domain's A/AAAA record must point at the server.

## Notes on IP certificates

Let's Encrypt issues IP certificates only with the `shortlived` profile
(≈6 days). The renewal timer runs twice daily and reloads nginx on renewal, so
no manual action is needed. If you later add a domain, re-run with `--domain`
and the vhost switches to the standard 90-day certificate.

## Browser trust

Domain and IP certificates issued here are **publicly trusted** — no browser
warning. (A self-signed bootstrap certificate is used only for the few seconds
between starting nginx and the first issuance.)
