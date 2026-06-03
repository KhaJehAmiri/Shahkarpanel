from app.events import EventType, publish, subscribe
from app.models.admin import Admin
from app.utils.notification import Notification, UserDeleted, notify


def test_publish_subscribe_with_type_filter():
    seen = []
    subscribe(lambda e: seen.append(e.type), types=[EventType.node_error])

    publish(EventType.node_error, {"node_id": 1})
    publish(EventType.node_connected, {"node_id": 2})  # filtered out

    assert seen == [EventType.node_error]


def test_subscriber_exception_does_not_break_publish():
    def boom(_event):
        raise RuntimeError("boom")

    seen = []
    subscribe(boom, types=[EventType.node_deleted])
    subscribe(lambda e: seen.append(e.type), types=[EventType.node_deleted])

    publish(EventType.node_deleted, {"node_id": 9})
    assert seen == [EventType.node_deleted]


def test_notification_is_bridged_to_event_bus():
    got = []
    subscribe(lambda e: got.append(e.type), types=[EventType.user_deleted])

    notify(
        UserDeleted(
            username="u1",
            action=Notification.Type.user_deleted,
            by=Admin(username="adm", is_sudo=True),
        )
    )
    assert EventType.user_deleted in got
