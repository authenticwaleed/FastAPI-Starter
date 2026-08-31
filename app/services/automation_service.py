import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    AutomationAlreadyExistsError,
    AutomationNotFoundError,
    InvalidAutomationSettingsError,
)
from app.db.session import SessionDep
from app.models.automation import (
    Automation,
    AutomationKind,
    AutomationRun,
    AutomationTrigger,
    RunStatus,
)
from app.models.workspace import Workspace
from app.repositories.automation_repository import AutomationRepository
from app.schemas.automation import AutomationCreate, AutomationUpdate
from app.services.automations import (
    CATALOGUE,
    Outcome,
    Tools,
    Trigger,
    UnansweredLeadFollowup,
)
from app.services.contact_service import ContactRepositoryDep
from app.services.conversation_service import (
    ConversationEventRepositoryDep,
    ConversationRepositoryDep,
)
from app.services.message_service import MessageRepositoryDep, MessageServiceDep
from app.services.order_service import OrderRepositoryDep
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)


class AutomationService:
    """Configuring the predefined automations, and running them.

    Two callers with two shapes. The dashboard turns one on, edits what it
    says and reads its history, always through a WorkspaceAccess that has
    already been checked. The engine runs them, from a background task,
    with no user anywhere -- which is why `fire` takes a Workspace rather
    than an access, and why nothing it does needs a role.
    """

    def __init__(
        self,
        session: Session,
        automations: AutomationRepository,
        tools: Tools,
    ) -> None:
        self._session = session
        self._automations = automations
        self._tools = tools

    # --- configuring -------------------------------------------------------

    def create(
        self,
        access: WorkspaceAccess,
        payload: AutomationCreate,
    ) -> Automation:
        """Switch a predefined automation on for this workspace.

        `kind` names one of the three that exist rather than describing a
        new one, and its settings are validated against the schema that
        automation declares -- so a row cannot be written that the code
        reading it will not understand.
        """
        workspace_id = access.workspace.id
        automation = CATALOGUE[payload.kind]
        definition = self._validated(payload.kind, payload.definition)

        try:
            created = self._automations.create(
                workspace_id=workspace_id,
                kind=payload.kind,
                name=payload.name or automation.default_name,
                trigger_type=automation.trigger,
                status=payload.status,
                definition=definition,
            )
            self._session.commit()
        except IntegrityError as exc:
            # One configuration per kind per workspace. Two order
            # confirmations would be two messages about one purchase.
            self._session.rollback()
            raise AutomationAlreadyExistsError(workspace_id, payload.kind) from exc

        return created

    def list_for(self, access: WorkspaceAccess) -> Sequence[Automation]:
        return self._automations.list_for_workspace(access.workspace.id)

    def get(self, access: WorkspaceAccess, automation_id: uuid.UUID) -> Automation:
        return self._require(access, automation_id)

    def update(
        self,
        access: WorkspaceAccess,
        automation_id: uuid.UUID,
        payload: AutomationUpdate,
    ) -> Automation:
        automation = self._require(access, automation_id)
        definition = (
            self._validated(automation.kind, payload.definition)
            if payload.definition is not None
            else None
        )

        self._automations.update(
            automation,
            name=payload.name,
            status=payload.status,
            definition=definition,
        )
        self._session.commit()

        return automation

    def delete(self, access: WorkspaceAccess, automation_id: uuid.UUID) -> None:
        """Remove it, and its history with it.

        A hard delete rather than a disable, because `disabled` is already
        a status and a business that wants the history kept has a way to
        say so. Two ways of switching something off, one of which throws
        the record away invisibly, would be one too many.
        """
        self._automations.delete(self._require(access, automation_id))
        self._session.commit()

    def runs_for(
        self,
        access: WorkspaceAccess,
        automation_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: RunStatus | None = None,
    ) -> tuple[Sequence[AutomationRun], int]:
        workspace_id = access.workspace.id
        self._require(access, automation_id)

        runs = self._automations.list_runs(
            workspace_id,
            automation_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            status=status,
        )
        total = self._automations.count_runs(
            workspace_id,
            automation_id,
            status=status,
        )

        return runs, total

    # --- running -----------------------------------------------------------

    def fire(self, workspace: Workspace, trigger: Trigger) -> list[AutomationRun]:
        """Consider every enabled automation for what just happened.

        Called from background tasks and never from a request, because
        what an automation does is send messages to customers -- and a
        provider taking four seconds must not be four seconds a webhook
        spends before acknowledging.

        Returns the runs it recorded, which is what a test asserts on and
        what the caller logs. Nothing is raised: one automation failing is
        recorded as a failed run and does not stop the next one, because
        the alternative is a keyword handoff that silently stops working
        the day an unrelated confirmation template breaks.
        """
        runs = []

        for automation in self._automations.list_enabled_for(
            workspace.id,
            trigger.type,
        ):
            run = self._execute(workspace, automation, trigger)

            if run is not None:
                runs.append(run)

        return runs

    def run_due(self, workspace: Workspace) -> list[AutomationRun]:
        """Run the automations that nothing fires.

        A follow-up is not about something happening; it is about
        something failing to happen, so it has to be looked for. This is
        the sweep that does the looking, and it is the entry point a
        scheduler will call -- the background-jobs phase supplies the
        timer, and nothing here changes when it does.
        """
        runs = []

        for automation in self._automations.list_enabled_for(
            workspace.id,
            AutomationTrigger.SCHEDULE,
        ):
            handler = CATALOGUE[automation.kind]

            if not isinstance(handler, UnansweredLeadFollowup):
                continue

            settings = handler.settings_model.model_validate(automation.definition)

            for conversation in handler.due(self._tools, workspace, settings):
                run = self._execute(
                    workspace,
                    automation,
                    Trigger(
                        type=AutomationTrigger.SCHEDULE,
                        workspace=workspace,
                        conversation_id=conversation.id,
                    ),
                )

                if run is not None:
                    runs.append(run)

        return runs

    def _execute(
        self,
        workspace: Workspace,
        automation: Automation,
        trigger: Trigger,
    ) -> AutomationRun | None:
        """One automation, once, with the run recorded either way.

        The claim comes first. `start_run` writes the row that the unique
        index on (automation_id, dedupe_key) will refuse a second time, so
        a redelivered webhook loses the race here rather than halfway
        through sending a message. Committed immediately, and that
        commit is the claim: held open, a second worker would not see it.
        """
        handler = CATALOGUE[automation.kind]

        try:
            run = self._automations.start_run(
                workspace_id=workspace.id,
                automation_id=automation.id,
                dedupe_key=handler.dedupe_key(trigger),
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            logger.info(
                "Automation %s has already run for this one", automation.kind.value
            )

            return None

        settings = handler.settings_model.model_validate(automation.definition)
        outcome, attempts, error = self._attempt(handler, trigger, settings)

        self._automations.finish_run(
            run,
            status=_status_of(outcome, error),
            at=datetime.now(UTC),
            attempts=attempts,
            error=error,
            meta=outcome.detail if outcome else {},
        )
        self._session.commit()

        return run

    def _attempt(
        self,
        handler: Any,
        trigger: Trigger,
        settings: Any,
    ) -> tuple[Outcome | None, int, str | None]:
        """Run it, retrying what is worth retrying.

        The retry policy is the automation's own, because what is worth a
        second go differs: a message the provider briefly refused is, and
        a template that will not render is not. Only AppError is retried,
        which is this application's own vocabulary for "something outside
        said no"; anything else is a bug and retrying a bug three times
        produces three of the same stack trace.

        Inline, and that is honest rather than ideal. This already runs
        after its response, so there is nobody waiting -- but it does mean
        the last attempt is the last attempt, and a provider down for a
        minute produces a failed run rather than one that resumes. The row
        it leaves is what a retry worker would pick up.
        """
        error: str | None = None

        for attempt in range(1, handler.max_attempts + 1):
            try:
                return handler.run(self._tools, trigger, settings), attempt, None
            except AppError as exc:
                error = str(exc)
                self._session.rollback()
                logger.warning(
                    "Automation %s failed on attempt %s: %s",
                    handler.kind.value,
                    attempt,
                    exc,
                )
            except Exception:
                self._session.rollback()
                logger.exception("Automation %s raised", handler.kind.value)

                return None, attempt, "internal error"

        return None, handler.max_attempts, error

    # --- shared ------------------------------------------------------------

    def _validated(
        self,
        kind: AutomationKind,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Settings, checked against the automation that will read them.

        Stored as what the model produced rather than as what arrived, so
        a definition always carries its defaults explicitly -- which is
        what makes the stored row answer "what will this say?" without
        anybody having to know the code's defaults.
        """
        try:
            settings = CATALOGUE[kind].settings_model.model_validate(definition)
        except ValidationError as exc:
            raise InvalidAutomationSettingsError(kind, exc.error_count()) from exc

        return settings.model_dump(mode="json")

    def _require(
        self,
        access: WorkspaceAccess,
        automation_id: uuid.UUID,
    ) -> Automation:
        automation = self._automations.get(access.workspace.id, automation_id)

        if automation is None:
            raise AutomationNotFoundError(access.workspace.id, automation_id)

        return automation


def _status_of(outcome: Outcome | None, error: str | None) -> RunStatus:
    if outcome is None:
        return RunStatus.FAILED

    return RunStatus.SUCCEEDED if outcome.ran else RunStatus.SKIPPED


def get_automation_repository(session: SessionDep) -> AutomationRepository:
    return AutomationRepository(session)


AutomationRepositoryDep = Annotated[
    AutomationRepository,
    Depends(get_automation_repository),
]


def get_automation_service(
    session: SessionDep,
    automations: AutomationRepositoryDep,
    messages: MessageServiceDep,
    message_repository: MessageRepositoryDep,
    conversations: ConversationRepositoryDep,
    events: ConversationEventRepositoryDep,
    contacts: ContactRepositoryDep,
    orders: OrderRepositoryDep,
) -> AutomationService:
    return AutomationService(
        session=session,
        automations=automations,
        tools=Tools(
            session=session,
            messages=messages,
            message_repository=message_repository,
            conversations=conversations,
            events=events,
            contacts=contacts,
            orders=orders,
            automations=automations,
        ),
    )


AutomationServiceDep = Annotated[
    AutomationService,
    Depends(get_automation_service),
]
