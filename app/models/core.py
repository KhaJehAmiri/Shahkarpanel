from pydantic import BaseModel


class CoreStats(BaseModel):
    version: str
    started: bool
    logs_websocket: str
    startup_error: str | None = None
    failed_inbound_tag: str | None = None
    failed_port: int | None = None
