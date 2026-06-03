# Contributing to NexusPanel

Thank you for helping improve NexusPanel.

## Getting started

1. Fork [KhaJehAmiri/nexuspanel](https://github.com/KhaJehAmiri/nexuspanel) on GitHub.
2. Clone your fork and create a branch.
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and run `alembic upgrade head`.
5. Run tests: `python3 -m pytest -q` and `python3 -m ruff check app/ tests/`

## Dashboard changes

```bash
cd app/dashboard
npm install
npm run dev    # http://localhost:3000
npm run build  # output → app/dashboard/build/
```

## Pull requests

- Keep changes focused; one feature or fix per PR.
- Update README (all languages) if user-facing behaviour changes.
- Add tests for new backend logic when practical.
- Do not commit secrets (`.env`, keys, certificates).

## Code style

- Python: Ruff (see `.ruff.toml`)
- TypeScript/React: existing Chakra + Vite conventions in `app/dashboard/`

## Questions

Open a [GitHub issue](https://github.com/KhaJehAmiri/nexuspanel/issues) for bugs and feature requests.
