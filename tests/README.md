# Tests

Pytest suite for NexusPanel. **Safe to publish** — no secrets or production data.

| File | Purpose |
|------|---------|
| `conftest.py` | Temp SQLite DB + stub `xray` binary (isolated from your server) |
| `test_phase*.py` | Feature tests per development phase |
| `test_*.py` | Event bus, rules, backup, metrics, etc. |

```bash
python3 -m pytest -q
```

See [SECURITY.md](../SECURITY.md) for why this folder belongs on GitHub.
