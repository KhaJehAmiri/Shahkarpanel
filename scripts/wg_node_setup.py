"""Create one WireGuard node + server config for QA. Prints the node id."""
import json
import sys
import uuid

from app.db import GetDB, crud
from app.models.node import NodeCreate
from app.wireguard import generate_keypair

name = sys.argv[1] if len(sys.argv) > 1 else f"wg-qa-{uuid.uuid4().hex[:6]}"
endpoint = sys.argv[2] if len(sys.argv) > 2 else "212.100.171.208:51820"

with GetDB() as db:
    priv, pub = generate_keypair()
    node = crud.create_node(db, NodeCreate(
        name=name, address="127.0.0.1", port=62050, api_port=62051,
        core_kind="wireguard",
    ))
    crud.set_node_wireguard(
        db, node, interface="wg0", listen_port=51820, subnet="10.20.0.0/24",
        private_key=priv, public_key=pub, endpoint=endpoint, mtu=1420, dns="1.1.1.1",
    )
    print(json.dumps({"node_id": node.id, "name": node.name, "server_pub": pub}))
