from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.db import Session, get_db
from app.db.models import Workflow
from app.events import EventType
from app.models.admin import Admin
from app.rules import available_actions
from app.utils import responses

router = APIRouter(
    tags=["Workflows"],
    prefix="/api/workflows",
    responses={401: responses._401, 403: responses._403},
)


class WorkflowStep(BaseModel):
    action: str
    params: Optional[dict] = None


class WorkflowCreate(BaseModel):
    name: str
    trigger_event: EventType
    steps: List[WorkflowStep]
    enabled: bool = True
    condition: Optional[dict] = None


class WorkflowModify(BaseModel):
    name: Optional[str] = None
    trigger_event: Optional[EventType] = None
    steps: Optional[List[WorkflowStep]] = None
    enabled: Optional[bool] = None
    condition: Optional[dict] = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    trigger_event: str
    steps: list
    enabled: bool
    condition: Optional[dict] = None
    created_at: datetime


def _validate_steps(steps: List[WorkflowStep]) -> list:
    actions = available_actions()
    for step in steps:
        if step.action not in actions:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action '{step.action}'. Available: {actions}",
            )
    return [s.model_dump() for s in steps]


@router.get("", response_model=List[WorkflowResponse])
def list_workflows(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    return db.query(Workflow).order_by(Workflow.id).all()


@router.post("", response_model=WorkflowResponse)
def create_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    workflow = Workflow(
        name=body.name,
        trigger_event=body.trigger_event.value,
        steps=_validate_steps(body.steps),
        enabled=body.enabled,
        condition=body.condition,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def modify_workflow(
    workflow_id: int,
    body: WorkflowModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if body.name is not None:
        workflow.name = body.name
    if body.trigger_event is not None:
        workflow.trigger_event = body.trigger_event.value
    if body.steps is not None:
        workflow.steps = _validate_steps(body.steps)
    if body.enabled is not None:
        workflow.enabled = body.enabled
    if body.condition is not None:
        workflow.condition = body.condition

    db.commit()
    db.refresh(workflow)
    return workflow


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.delete(workflow)
    db.commit()
    return {}
