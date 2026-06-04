from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import feature_flags
from app.db import Session, get_db
from app.db.models import Rule
from app.events import EventType
from app.models.admin import Admin
from app.rules import available_actions
from app.utils import responses

router = APIRouter(
    tags=["Rules"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


class RuleCreate(BaseModel):
    name: str
    trigger_event: EventType
    action: str
    enabled: bool = True
    condition: Optional[dict] = None
    action_params: Optional[dict] = None


class RuleModify(BaseModel):
    name: Optional[str] = None
    trigger_event: Optional[EventType] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None
    condition: Optional[dict] = None
    action_params: Optional[dict] = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    trigger_event: str
    action: str
    enabled: bool
    condition: Optional[dict] = None
    action_params: Optional[dict] = None
    created_at: datetime


def _require_enabled():
    if not feature_flags.is_enabled("rule_engine"):
        raise HTTPException(status_code=404, detail="Rule engine is disabled")


def _validate_action(action: str) -> None:
    if action not in available_actions():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{action}'. Available: {available_actions()}",
        )


@router.get("/rules", response_model=List[RuleResponse])
def list_rules(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    _require_enabled()
    return db.query(Rule).order_by(Rule.id).all()


@router.post("/rules", response_model=RuleResponse)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    _validate_action(body.action)
    rule = Rule(
        name=body.name,
        trigger_event=body.trigger_event.value,
        action=body.action,
        enabled=body.enabled,
        condition=body.condition,
        action_params=body.action_params,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=RuleResponse)
def modify_rule(
    rule_id: int,
    body: RuleModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.action is not None:
        _validate_action(body.action)
        rule.action = body.action
    if body.name is not None:
        rule.name = body.name
    if body.trigger_event is not None:
        rule.trigger_event = body.trigger_event.value
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.condition is not None:
        rule.condition = body.condition
    if body.action_params is not None:
        rule.action_params = body.action_params

    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {}
