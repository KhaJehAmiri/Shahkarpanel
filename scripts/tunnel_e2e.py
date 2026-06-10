"""Tunnel E2E helper — creates a relay→exit tunnel row and prints apply checklist.

Runs in-process against the live DB. Does not apply to live Xray cores unless
you call POST /api/tunnels/{id}/apply with an admin token afterward.

Usage:
  python3 scripts/tunnel_e2e.py
  python3 scripts/tunnel_e2e.py --relay-node 1 --exit-node 2
"""
import argparse
import json
import uuid

from app import feature_flags, tunnel as tunnel_svc
from app.db import GetDB, crud
from app.db.models import Tunnel


def main():
    parser = argparse.ArgumentParser(description="Tunnel E2E DB setup + config preview")
    parser.add_argument("--relay-node", type=int, default=1, help="Relay node id (Iran)")
    parser.add_argument("--exit-node", type=int, default=None, help="Exit node id (foreign); omit for panel exit")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    out = {"flags": {}}
    out["flags"]["tunneling"] = feature_flags.is_enabled("tunneling")
    if not out["flags"]["tunneling"]:
        out["hint"] = "Enable flag: System → Feature flags → tunneling"

    with GetDB() as db:
        relay = crud.get_node_by_id(db, args.relay_node) if args.relay_node else None
        exit_node = crud.get_node_by_id(db, args.exit_node) if args.exit_node else None
        out["relay_node"] = {"id": relay.id, "name": relay.name, "address": relay.address} if relay else None
        out["exit_node"] = (
            {"id": exit_node.id, "name": exit_node.name, "address": exit_node.address}
            if exit_node
            else {"kind": "panel", "hint": "Set PANEL_PUBLIC_ADDRESS for exit address"}
        )

        t = Tunnel(
            name=args.name or f"tunnel-e2e-{uuid.uuid4().hex[:6]}",
            enabled=True,
            relay_node_id=args.relay_node,
            exit_node_id=args.exit_node,
            transport="reality",
            listen_port=443,
            target_port=8443,
            params=tunnel_svc.default_params("reality"),
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        out["tunnel_id"] = t.id

        exit_addr = exit_node.address if exit_node else "PANEL_PUBLIC_ADDRESS"
        pair = tunnel_svc.build_tunnel_pair(t, exit_address=exit_addr)
        out["relay_outbound_tag"] = pair["relay"]["outbound"].get("tag")
        out["exit_inbound_port"] = pair["exit"]["inbound"].get("port")

    out["apply"] = f"POST /api/tunnels/{out['tunnel_id']}/apply  (admin Bearer token)"
    out["verify"] = [
        "Client connects to relay user inbound",
        "Egress IP on exit node is foreign",
        f"GET /api/tunnels/{out['tunnel_id']}/config for JSON fragments",
    ]
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
