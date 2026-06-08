"""Runtime capability probes for WireGuard nodes."""
from app.wireguard.operations import _node_object
from app.wireguard.transport import client_for_node


def node_amnezia_available(dbnode) -> bool:
    """True when the connected node agent reports amneziawg-go + awg tools."""
    client = client_for_node(_node_object(dbnode.id))
    if client is None:
        return False
    return client.amnezia_available()
