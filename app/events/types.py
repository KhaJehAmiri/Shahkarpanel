from enum import Enum


class EventType(str, Enum):
    """Canonical event types published on the NexusPanel event bus.

    User lifecycle values intentionally mirror
    ``app.utils.notification.Notification.Type`` so existing notifications map
    onto the bus without translation. Node lifecycle events are new and let
    plugins, webhooks and the (future) rule engine react to cluster changes.
    """

    # User lifecycle
    user_created = "user_created"
    user_updated = "user_updated"
    user_deleted = "user_deleted"
    user_limited = "user_limited"
    user_expired = "user_expired"
    user_enabled = "user_enabled"
    user_disabled = "user_disabled"
    data_usage_reset = "data_usage_reset"
    data_reset_by_next = "data_reset_by_next"
    subscription_revoked = "subscription_revoked"
    reached_usage_percent = "reached_usage_percent"
    reached_days_left = "reached_days_left"

    # Node lifecycle
    node_created = "node_created"
    node_modified = "node_modified"
    node_deleted = "node_deleted"
    node_connected = "node_connected"
    node_error = "node_error"
    node_down = "node_down"
    node_recovered = "node_recovered"

    # Traffic intelligence (phase 5)
    heavy_user_detected = "heavy_user_detected"
    usage_anomaly = "usage_anomaly"
    bandwidth_exhaustion_predicted = "bandwidth_exhaustion_predicted"
    node_at_risk = "node_at_risk"

    @classmethod
    def from_value(cls, value: str):
        try:
            return cls(value)
        except ValueError:
            return None
