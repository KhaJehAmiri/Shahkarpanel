# SigmaGuard Wire (internal)

Private UDP transport for the SigmaGuard app. **Not** exposed on `/sub/` public subscription.

## Enable

1. Wire sources live at `/opt/sigmaguard/wire` (inside the SigmaGuard repo)
2. Set `SIGMAGUARD_WIRE_ROOT=/opt/sigmaguard/wire` in `.env` (optional; auto-detected)
3. **System → Feature flags → SigmaGuard Wire (private)** → enable
4. WireGuard node must have AmneziaWG stack enabled (reuses `awg_listen_port` / subnet)

## Client API

When enabled, `GET /api/v2/client/config` may include:

```json
"protocol_materials": {
  "sigmaguard-wire": {
    "conf": "[Interface]…",
    "preset_rev": "sg-wire-1",
    "engine": "sigmaguard-wire",
    "node_id": 1
  }
}
```

Negotiate prioritises `sigmaguard-wire` for **gamer** profile when UDP is available.

## Code

| Module | Role |
|--------|------|
| `app/sigmaguard_wire/bridge.py` | Loads presets from `SIGMAGUARD_WIRE_ROOT` |
| `app/client/materials.py` | Builds conf for Client API only |
| `app/client/__init__.py` | Protocol priority |

## See also

- `/opt/sigmaguard/wire/INTEGRATION.md`
- `/opt/WORKSPACE.md`
- `/opt/SIGMAGUARD_HANDOFF.md`
