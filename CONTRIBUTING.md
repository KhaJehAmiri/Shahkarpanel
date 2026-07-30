# Contributing to Shahkar

Thank you for helping improve Shahkar.

## Getting started

1. Fork [KhaJehAmiri/Shahkarpanel](https://github.com/KhaJehAmiri/Shahkarpanel) on GitHub.
2. Clone your fork and create a branch.
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and run `alembic upgrade head`.
5. Run tests: `python3 -m pytest -q` and `python3 -m ruff check app/ tests/`

## Dashboard changes

The UI lives in `app/dashboard-next` (Next.js static export).

```bash
./build_dashboard.sh
# or:
cd app/dashboard-next && npm install && NEXT_PUBLIC_BASE_API=/api/ npm run dev
```

Built assets are served from `app/dashboard-next/out/` (see `app/dashboard/__init__.py`).

## Pull requests

- Keep changes focused; one feature or fix per PR.
- Update README (all languages) if user-facing behaviour changes.
- Add tests for new backend logic when practical.
- Do not commit secrets (`.env`, keys, certificates).

## Code style

- Python: Ruff (see `.ruff.toml`)
- TypeScript/React: Next.js + panel components under `app/dashboard-next/src/panel/`

## Questions

Open a [GitHub issue](https://github.com/KhaJehAmiri/Shahkarpanel/issues) for bugs and feature requests.
