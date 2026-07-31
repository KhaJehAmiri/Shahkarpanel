#!/usr/bin/env python3
"""Prepare isolated demo entities for a 5-minute sales pitch.

Idempotent — safe to re-run. Does NOT complete payments (those are shown live).

Creates / resets:
  - reseller  demo_reseller
  - plan      «دمو ارائه» (owned by demo_reseller)
  - portal user demo_portal (login to /portal/)

Usage (on the panel host):
  docker exec -u shahkar -w /code -e PYTHONPATH=/code \\
    shahkar-shahkar-1 python scripts/prepare_demo_seed.py
"""

from __future__ import annotations

import sys

RESELLER_USER = "demo_reseller"
RESELLER_PASS = "DemoReseller1!"
PORTAL_USER = "demo_portal"
PORTAL_PASS = "DemoPortal1!"
PLAN_NAME = "دمو ارائه"
PLAN_PRICE = 50_000  # minor units (تومان if currency is toman)
PLAN_DAYS = 30
PLAN_BYTES = 10 * 1024**3  # 10 GiB


def main() -> int:
    from app.db import GetDB, crud
    from app.db.models import Admin, Plan, User
    from app.models.admin import AdminCreate, pwd_context
    from app.models.user import UserCreate, UserStatusCreate
    from app import billing
    from app import platform_settings as ps
    from app.middleware.dashboard_path import custom_dashboard_path
    from config import PANEL_PUBLIC_ADDRESS

    with GetDB() as db:
        sudo = (
            db.query(Admin)
            .filter(Admin.is_sudo.is_(True))
            .order_by(Admin.id)
            .first()
        )
        if sudo is None:
            print("ERROR: no sudo admin found", file=sys.stderr)
            return 1

        # --- Reseller ---
        reseller = crud.get_admin(db, RESELLER_USER)
        if reseller is None:
            reseller = crud.create_admin(
                db,
                AdminCreate(
                    username=RESELLER_USER,
                    password=RESELLER_PASS,
                    is_sudo=False,
                    role="reseller",
                ),
            )
            print(f"+ created reseller {RESELLER_USER}")
        else:
            reseller.hashed_password = pwd_context.hash(RESELLER_PASS)
            reseller.role = reseller.role or "reseller"
            reseller.is_sudo = False
            db.commit()
            db.refresh(reseller)
            print(f"* reset password for reseller {RESELLER_USER}")

        # Small wallet so overview is not empty (top-up demo still shown live).
        wallet = billing.get_or_create_wallet(db, reseller.id)
        if int(wallet.balance or 0) < 100_000:
            billing.add_transaction(
                db,
                reseller.id,
                500_000,
                type="credit",
                description="Demo seed credit",
                skip_commission=True,
            )
            print("+ credited reseller wallet +500,000")

        # --- Plan (reseller-owned catalog) ---
        plan = (
            db.query(Plan)
            .filter(
                Plan.name == PLAN_NAME,
                Plan.owner_admin_id == reseller.id,
            )
            .first()
        )
        if plan is None:
            plan = crud.create_plan(
                db,
                tenant_id=reseller.tenant_id,
                owner_admin_id=reseller.id,
                name=PLAN_NAME,
                price=PLAN_PRICE,
                data_limit=PLAN_BYTES,
                duration_days=PLAN_DAYS,
                device_limit=2,
                enabled=True,
            )
            print(f"+ created plan {PLAN_NAME} id={plan.id}")
        else:
            plan.price = PLAN_PRICE
            plan.data_limit = PLAN_BYTES
            plan.duration_days = PLAN_DAYS
            plan.enabled = True
            db.commit()
            db.refresh(plan)
            print(f"* refreshed plan {PLAN_NAME} id={plan.id}")

        # --- Portal login user ---
        portal = crud.get_user(db, PORTAL_USER)
        if portal is None:
            portal = crud.create_user(
                db,
                UserCreate(
                    username=PORTAL_USER,
                    status=UserStatusCreate.active,
                    proxies={"vless": {}},
                    data_limit=PLAN_BYTES,
                    expire=None,
                    note="demo seed — portal login",
                    portal_enabled=True,
                    portal_password=PORTAL_PASS,
                ),
                admin=reseller,
            )
            print(f"+ created portal user {PORTAL_USER}")
        else:
            portal.admin_id = reseller.id
            crud.set_portal_password(db, portal, PORTAL_PASS)
            if hasattr(portal, "must_change_credentials"):
                portal.must_change_credentials = False
            db.commit()
            print(f"* reset portal password for {PORTAL_USER}")

        card_ok = ps.get_bool("payment.card_enabled") and bool(
            (ps.get_str("payment.card_number") or "").strip()
        )
        base = (PANEL_PUBLIC_ADDRESS or "").rstrip("/") or "https://YOUR-HOST"
        dash = custom_dashboard_path().rstrip("/")

        print()
        print("=" * 56)
        print("DEMO SEED READY")
        print("=" * 56)
        print(f"Owner (sudo):     {sudo.username}  (existing password)")
        print(f"Reseller:         {RESELLER_USER} / {RESELLER_PASS}")
        print(f"Portal user:      {PORTAL_USER} / {PORTAL_PASS}")
        print(f"Plan:             {PLAN_NAME}  #{plan.id}  price={PLAN_PRICE}")
        print(f"Platform card:    {'OK' if card_ok else 'MISSING — set System → Commercial'}")
        print()
        print(f"Panel URL:        {base}{dash}/")
        print(f"Portal URL:       {base}/portal/")
        print()
        print("Pitch order: see docs/DEMO_SCRIPT_FA.md")
        print("=" * 56)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
