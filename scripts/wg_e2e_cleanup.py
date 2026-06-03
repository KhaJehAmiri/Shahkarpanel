"""Remove Phase 11.7 E2E throwaway artifacts (wg-e2e node + wgok*/wglim* users)."""
from app.db import GetDB
from app.db.models import Node, NodeWireGuard, Proxy, User

removed = {"users": [], "nodes": []}
with GetDB() as db:
    for u in db.query(User).filter(
        (User.username.like("wgok%")) | (User.username.like("wglim%"))
    ).all():
        db.query(Proxy).filter(Proxy.user_id == u.id).delete()
        removed["users"].append(u.username)
        db.delete(u)
    for n in db.query(Node).filter(Node.name.like("wg-e2e-%")).all():
        db.query(NodeWireGuard).filter(NodeWireGuard.node_id == n.id).delete()
        removed["nodes"].append(n.name)
        db.delete(n)
    db.commit()
print(removed)
