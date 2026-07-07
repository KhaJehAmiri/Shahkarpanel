#!/usr/bin/env python3
"""Remove migrated panel data (users, endpoints, inbounds) for a clean re-import."""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, "/code")

import commentjson
from sqlalchemy import or_

from app.db import GetDB, crud
from app.db.models import (
    NextPlan,
    NodeUserProtocolUsage,
    NodeUserUsage,
    NotificationReminder,
    Proxy,
    ProxyHost,
    ProxyInbound,
    SubscriptionEndpoint,
    SubscriptionTokenAlias,
    User,
    UserUsageResetLogs,
    excluded_inbounds_association,
)
from config import XRAY_JSON


def _user_ids(db, slug_prefixes: list[str]) -> list[int]:
    ids: set[int] = set()
    for prefix in slug_prefixes:
        for row in db.query(User.id).filter(User.username.like(f"{prefix}%")).all():
            ids.add(row[0])
    return sorted(ids)


def _delete_users(db, user_ids: list[int]) -> int:
    if not user_ids:
        return 0
    db.query(SubscriptionTokenAlias).filter(SubscriptionTokenAlias.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(NodeUserProtocolUsage).filter(NodeUserProtocolUsage.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(NodeUserUsage).filter(NodeUserUsage.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(NotificationReminder).filter(NotificationReminder.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(UserUsageResetLogs).filter(UserUsageResetLogs.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(NextPlan).filter(NextPlan.user_id.in_(user_ids)).delete(synchronize_session=False)
    proxy_ids = [
        row[0] for row in db.query(Proxy.id).filter(Proxy.user_id.in_(user_ids)).all()
    ]
    if proxy_ids:
        db.execute(
            excluded_inbounds_association.delete().where(
                excluded_inbounds_association.c.proxy_id.in_(proxy_ids)
            )
        )
    db.query(Proxy).filter(Proxy.user_id.in_(user_ids)).delete(synchronize_session=False)
    deleted = db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()
    return deleted


def _delete_inbound_tags(db, tags: list[str]) -> int:
    if not tags:
        return 0
    db.execute(
        excluded_inbounds_association.delete().where(
            excluded_inbounds_association.c.inbound_tag.in_(tags)
        )
    )
    db.query(ProxyHost).filter(ProxyHost.inbound_tag.in_(tags)).delete(synchronize_session=False)
    deleted = (
        db.query(ProxyInbound)
        .filter(ProxyInbound.tag.in_(tags))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def _inbound_tags_for_prefixes(prefixes: tuple[str, ...]) -> list[str]:
    with GetDB() as db:
        tags = [row[0] for row in db.query(ProxyInbound.tag).all()]
    return [t for t in tags if any(t.startswith(p) for p in prefixes)]


def _auto_migration_slugs(db) -> list[str]:
    """All subscription routes except the built-in default route."""
    rows = db.query(SubscriptionEndpoint.slug).filter(SubscriptionEndpoint.slug != "default").all()
    bases: list[str] = []
    for (slug,) in rows:
        slug = str(slug)
        for suffix in ("-json", "-clash"):
            if slug.endswith(suffix):
                slug = slug[: -len(suffix)]
                break
        if slug not in bases:
            bases.append(slug)
    return bases


def _inbound_prefixes(slug_prefixes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        [f"{s}-" for s in slug_prefixes]
        + [f"{s}_" for s in slug_prefixes]
        + ["p4-in-"]
    ))


def _clean_xray_inbounds(tag_prefixes: tuple[str, ...]) -> list[str]:
    with open(XRAY_JSON, "r", encoding="utf-8") as f:
        raw = commentjson.loads(f.read())
    removed: list[str] = []
    kept = []
    for ib in raw.get("inbounds") or []:
        tag = str(ib.get("tag") or "")
        if any(tag.startswith(p) for p in tag_prefixes):
            removed.append(tag)
        else:
            kept.append(ib)
    if not removed:
        return removed
    raw["inbounds"] = kept
    with open(XRAY_JSON, "w", encoding="utf-8") as f:
        f.write(json.dumps(raw, indent=4))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean migrated panel data")
    parser.add_argument(
        "--slugs",
        nargs="+",
        help="Username/endpoint slug prefixes to remove (default: auto-detect from endpoints)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Remove every non-default subscription route and matching users/inbounds",
    )
    args = parser.parse_args()

    with GetDB() as db:
        if args.auto or not args.slugs:
            slug_prefixes = _auto_migration_slugs(db)
        else:
            slug_prefixes = [s.strip().rstrip("-_") for s in args.slugs if s.strip()]

        if not slug_prefixes:
            print("nothing to clean (no migration endpoints found)")
            return

        print(f"cleaning slugs: {slug_prefixes}")
        user_ids = _user_ids(db, slug_prefixes)
        users_deleted = _delete_users(db, user_ids)
        ep_patterns = [f"{s}%" for s in slug_prefixes]
        eps = (
            db.query(SubscriptionEndpoint)
            .filter(or_(*[SubscriptionEndpoint.slug.like(p) for p in ep_patterns]))
            .all()
        )
        ep_count = 0
        for ep in eps:
            crud.remove_subscription_endpoint(db, ep)
            ep_count += 1

        inbound_prefixes = _inbound_prefixes(slug_prefixes)
        db_tags = _inbound_tags_for_prefixes(inbound_prefixes)
        inbounds_deleted = _delete_inbound_tags(db, db_tags)

    removed_tags = _clean_xray_inbounds(inbound_prefixes)

    try:
        from app import xray
        from app.xray.config import XRayConfig

        with open(XRAY_JSON, encoding="utf-8") as f:
            raw = commentjson.loads(f.read())
        xray.config = XRayConfig(raw, api_port=xray.config.api_port)
        xray.core.restart(xray.config.include_db_users(), force=True)
    except Exception as exc:
        print(f"xray restart warning: {exc}")

    print(f"users_deleted={users_deleted}")
    print(f"endpoints_deleted={ep_count}")
    print(f"db_inbounds_deleted={inbounds_deleted}")
    print(f"xray_inbounds_removed={removed_tags}")


if __name__ == "__main__":
    main()
