# Unified Accounting Contract (Phase 11.0)

NexusPanel bills every protocol against **one** field: `User.used_traffic`,
capped by **one** `User.data_limit`. This document is the authoritative
description of how usage flows today and the invariants WireGuard (and any
future protocol/core) must respect so that **a single client can use every
protocol while one central quota stays accurate**.

The invariants below are locked by `tests/test_unified_accounting.py`. Those
tests must keep passing unchanged after WireGuard usage is added.

## Data model

- One `User` has one `used_traffic` (`BigInteger`) and one optional
  `data_limit`. See `app/db/models.py` (`class User`).
- A `User` has many `Proxy` rows — one per enabled protocol
  (`vmess` / `vless` / `trojan` / `shadowsocks`, and — Phase 11 — `wireguard`).
  Proxies do **not** each carry a counter; they share the user's `used_traffic`.
- `NodeUserUsage` is an **hourly, per-node** breakdown for analytics. It is
  derived from the same numbers and must use the same `uid` and the same
  billable filter as the central counter.

## The single usage pipeline

All collection funnels through `app/jobs/record_usages.py`:

```
collect_user_usage_params()        # gather raw {uid, value} per source
        │
        ▼
aggregate_user_usage(api_params, usage_coefficient)
        │   users_usage[uid] += value * coefficient[source]
        ▼
record_aggregated_user_usages(...)
        │   filter to BILLABLE_STATUSES
        │   UPDATE users.used_traffic += value, online_at = now
        │   UPDATE admins.users_usage += value
        ▼   INSERT/UPDATE node_user_usages (hourly, per node)
```

`api_params` maps `source_id -> [{"uid": <User.id>, "value": <bytes>}, ...]`.
`source_id` is `None` for the local Xray core and the node id for each
connected node. **This shape is the integration contract**: every collector
(Xray `get_users_stats`, and the Phase 11 WireGuard transfer collector) emits
exactly this shape, so all bytes merge into one counter with no second DB
write path.

## Invariants (locked by tests)

1. **uid is the integer `User.id`.**
   - Xray: the stat email is `f"{user.id}.{username}"`; the collector takes
     `stat.name.split('.', 1)[0]`. Usernames may contain dots; only the first
     dot splits the id off.
   - WireGuard: peers have no email. The collector must map
     `public_key -> User.id` and emit the **same integer uid**.

2. **Coefficient is applied exactly once per source.** Multi-node merges
   multiply each source's bytes by `Node.usage_coefficient` once, during
   aggregation, and again (consistently) when writing `NodeUserUsage`.

3. **Only `active` and `on_hold` accrue.** `BILLABLE_STATUSES =
   (UserStatus.active, UserStatus.on_hold)`. Disabled / limited / expired users
   must not gain `used_traffic` or have `online_at` bumped — even if a source
   still reports bytes for them. (Provisioning removes such users from the data
   plane; this filter is the backstop.)

4. **Many protocols collapse to one counter.** Multiple stat lines for the same
   uid (e.g. one per protocol/inbound) sum into the single `used_traffic`.

5. **A second source merges centrally.** A separate node — including a future
   WireGuard node — reporting the same uid adds to the same `used_traffic`
   (with that node's coefficient). No per-protocol quota, no separate counter.

## Double-counting rule (WireGuard)

WireGuard traffic must be counted from **exactly one** source. Xray does **not**
emit `user>>>email` stats for WireGuard peers, so WireGuard runs as a native
interface on the node and is measured via `wg show <iface> transfer`
(`rx + tx` per public key), mapped to `uid` and injected into `api_params`.

**Never** also represent the same user as an Xray `wireguard` inbound peer for
billing — that would double-count the same bytes for one `User.id`.

### Cumulative → delta (Phase 11.4)

`wg show <iface> transfer` reports **cumulative** counters per peer, unlike
Xray's `get_users_stats(reset=True)` which zeroes on read. The WireGuard
collector (`app/wireguard/usage.py`) therefore converts cumulative readings to
per-interval **deltas** before emitting `{uid, value}`:

- First observation of a `(node_id, public_key)` only sets a baseline → delta 0
  (so traffic before the panel started watching is not back-billed; at most one
  poll interval is lost across a panel restart).
- A counter that goes **down** means the interface/peer was recreated (reset to
  0); the current value itself is the delta.
- The delta tracker is keyed per node and runs under `run_if_leader`, so only
  the leader accumulates baselines (consistent with the single writer).

Unknown public keys (no matching `User`) are dropped — unattributable bytes
must never land on the wrong account.

## Status / lifecycle sync

Whenever a user's billable status changes, the data plane must follow so the
billable filter and reality agree:

- create / enable / reset-to-active → add Xray clients **and** WireGuard peer.
- disable / limited / expired → remove Xray clients **and** WireGuard peer.

The hook is centralized: `app/xray/operations.py` (`add_user` / `update_user` /
`remove_user` / `remove_user_immediate`) calls `_sync_wireguard()`, which
re-converges every WireGuard node via `app/wireguard/operations.py`
(`sync_all_nodes`). Because those functions are the single choke point invoked
from the routers, Telegram, `review_users` and `reset_user_data_usage`, every
call site gets WireGuard peer sync for free.

## Tests

`tests/test_unified_accounting.py` covers: uid parsing with dotted usernames,
coefficient-applied-once, billable-only accrual across all five statuses,
multi-protocol single counter, second-source (WireGuard-style) merge, admin
roll-up, and empty no-op. Run:

```
python3 -m pytest tests/test_unified_accounting.py -q
```
