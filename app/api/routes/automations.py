import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.plan import REQUIRES_AUTOMATIONS
from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    AUTOMATION_CONFLICT,
    AUTOMATION_NOT_FOUND,
    BAD_AUTOMATION_SETTINGS,
    PLAN_REQUIRED,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.automation import RunStatus
from app.schemas.automation import (
    AutomationCreate,
    AutomationRead,
    AutomationUpdate,
    RunPage,
    RunRead,
    SweepReport,
)
from app.services.automation_service import AutomationServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/automations",
    tags=["automations"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Administration throughout. An automation sends messages to customers in
# the business's name without anybody reading them first, which is a
# decision about how the business speaks rather than a thing an agent
# adjusts between conversations. Reading is any member's: what the
# business has switched on, and what it has been doing, is not a secret
# from the people working in it.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        **SCOPED,
        **AUTOMATION_CONFLICT,
        **BAD_AUTOMATION_SETTINGS,
        **PLAN_REQUIRED,
    },
    # Gated on the plan rather than on a check inside the handler, which
    # is the plan's instruction for Phase 24 as one line. Only creating
    # is gated: a workspace that drops to a plan without automations
    # keeps being able to read and switch off what it already has, which
    # is the difference between losing a feature and losing your data.
    dependencies=[REQUIRES_AUTOMATIONS],
)
def create_automation(
    payload: AutomationCreate,
    access: WorkspaceAdminDep,
    service: AutomationServiceDep,
) -> AutomationRead:
    """Switch a predefined automation on for this workspace.

    The settings are validated against the automation named, so a
    definition that will not work is refused here rather than becoming a
    run that fails every time for a reason nobody can see.
    """
    return AutomationRead.model_validate(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_automations(
    access: WorkspaceMemberDep,
    service: AutomationServiceDep,
) -> list[AutomationRead]:
    """What this workspace has switched on, enabled or not.

    Unpaged: there are as many of these as there are predefined
    automations, and a page control over a list of three is furniture.
    """
    return [
        AutomationRead.model_validate(automation)
        for automation in service.list_for(access)
    ]


@router.post(
    "/run-due",
    responses={**SCOPED, **PLAN_REQUIRED},
    dependencies=[REQUIRES_AUTOMATIONS],
)
def run_due_automations(
    access: WorkspaceAdminDep,
    service: AutomationServiceDep,
) -> SweepReport:
    """Run the automations that nothing fires.

    A follow-up is not about something happening; it is about something
    failing to happen, so it has to be looked for rather than triggered.
    This is the sweep that looks.

    An endpoint rather than a timer, because there is no scheduler yet --
    that is the background-jobs phase, and what it will do is call this.
    Safe to call repeatedly: every run it records is deduplicated on the
    thing it acted on, so a second sweep a minute later finds the same
    dropped threads and correctly does nothing about them.
    """
    runs = service.run_due(access.workspace)

    return SweepReport(
        considered=len(runs),
        ran=len([run for run in runs if run.status is RunStatus.SUCCEEDED]),
    )


@router.get("/{automation_id}", responses={**SCOPED, **AUTOMATION_NOT_FOUND})
def read_automation(
    automation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: AutomationServiceDep,
) -> AutomationRead:
    return AutomationRead.model_validate(service.get(access, automation_id))


@router.patch(
    "/{automation_id}",
    responses={**SCOPED, **AUTOMATION_NOT_FOUND, **BAD_AUTOMATION_SETTINGS},
)
def update_automation(
    automation_id: uuid.UUID,
    payload: AutomationUpdate,
    access: WorkspaceAdminDep,
    service: AutomationServiceDep,
) -> AutomationRead:
    return AutomationRead.model_validate(service.update(access, automation_id, payload))


@router.delete(
    "/{automation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **AUTOMATION_NOT_FOUND},
)
def delete_automation(
    automation_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: AutomationServiceDep,
) -> None:
    """Remove it, and its history with it.

    `disabled` is already a status, so a business that wants the record
    kept has a way to say so.
    """
    service.delete(access, automation_id)


@router.get("/{automation_id}/runs", responses={**SCOPED, **AUTOMATION_NOT_FOUND})
def list_runs(
    automation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: AutomationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> RunPage:
    """What this automation has done, most recent first.

    Most rows are `skipped`, and that is the point rather than noise: an
    automation is considered on every matching event, so the history is
    also the record of everything it correctly left alone. Filter by
    `status` to see only the ones that did something -- or only the ones
    that failed, which is the question somebody usually arrives with.
    """
    runs, total = service.runs_for(
        access,
        automation_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )

    return RunPage(
        items=[RunRead.model_validate(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
    )
