import json
import logging

from .bus import Event, Sink

logger = logging.getLogger("uvicorn.error")

STREAM_KEY = "shahkar:events"
STREAM_MAXLEN = 50_000


def build_redis_sink(redis_url: str) -> Sink:
    """Create an event sink that appends every event to a Redis Stream.

    This makes events durable and consumable by other processes/panels, which
    is the foundation for High Availability. Local subscribers keep running
    in-process regardless of this sink.
    """
    import redis  # imported lazily so Redis stays an optional dependency

    client = redis.Redis.from_url(redis_url)
    # Fail fast if the URL is wrong, so misconfiguration surfaces at startup.
    client.ping()

    def sink(event: Event) -> None:
        client.xadd(
            STREAM_KEY,
            {
                "type": event.type.value,
                "payload": json.dumps(event.payload, default=str),
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )

    logger.info("Redis event sink connected (stream=%s)", STREAM_KEY)
    return sink
