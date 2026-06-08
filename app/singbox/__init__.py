"""Panel-side integration for the node sing-box engine (Hysteria2 / TUIC).

Mirrors ``app.wireguard``: a pure planner turns the panel's view of a sing-box
node (its inbound config plus the users holding a Hysteria2/TUIC proxy) into
the declarative spec consumed by the node agent's ``/singbox/apply`` endpoint,
and into the ``name -> User.id`` map that folds per-user traffic into the single
central ``User.used_traffic`` (see ``docs/accounting-contract.md``).
"""
