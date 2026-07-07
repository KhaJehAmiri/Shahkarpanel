"""WebSocket admin auth — bearer token in header only (not query string)."""
from fastapi import WebSocket


def ws_bearer_token(websocket: WebSocket) -> str:
    auth = websocket.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # Browser WebSocket API cannot set Authorization; allow token query param.
    return (websocket.query_params.get("token") or "").strip()
