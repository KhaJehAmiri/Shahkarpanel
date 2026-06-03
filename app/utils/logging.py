"""Structured logging helpers.

Adds a per-request correlation id (``request_id``) to every log record and,
when ``LOG_JSON`` is enabled, formats logs as single-line JSON suitable for log
aggregators (Loki, ELK, Datadog, ...). When disabled, behaviour is unchanged
apart from the request id being available on records.
"""
import json
import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates an X-Request-ID for each request."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def setup_structured_logging(json_logs: bool) -> None:
    """Attach the request-id filter (and optional JSON formatter) to loggers.

    Call after the logging handlers are configured (e.g. on app startup).
    """
    request_id_filter = RequestIdFilter()
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.addFilter(request_id_filter)
        for handler in logger.handlers:
            handler.addFilter(request_id_filter)
            if json_logs:
                handler.setFormatter(JsonFormatter())
