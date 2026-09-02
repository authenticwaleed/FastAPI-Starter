import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plan_override import PlanOverride
from app.services.plans import PlanTier


class PlanOverrideRepository:
    """Every query against the plan_overrides table lives here.

    `applying_to` runs wherever a plan is resolved, which is on most
    authenticated requests -- so it is one indexed lookup on the unique
    workspace column, with the expiry compared in the database.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_workspace(self, workspace_id: uuid.UUID) -> PlanOverride | None:
        """The override on this workspace, in force or not.

        Both, because the console has to be able to show an expired one:
        "this was comped until March" is the answer to why a customer
        remembers having a feature they no longer have.
        """
        return self._session.scalar(
            select(PlanOverride).where(PlanOverride.workspace_id == workspace_id)
        )

    def applying_to(
        self,
        workspace_id: uuid.UUID,
        now: datetime,
    ) -> PlanOverride | None:
        """The override actually entitling this workspace right now.

        Nothing runs to expire one. A row with a date behind it stops
        matching here, which is what makes "an expired override stops
        applying without anything having to run" true rather than
        aspirational.
        """
        return self._session.scalar(
            select(PlanOverride).where(
                PlanOverride.workspace_id == workspace_id,
                (PlanOverride.expires_at.is_(None)) | (PlanOverride.expires_at > now),
            )
        )

    def upsert(
        self,
        *,
        workspace_id: uuid.UUID,
        plan: PlanTier,
        reason: str,
        granted_by_user_id: int | None,
        expires_at: datetime | None,
    ) -> PlanOverride:
        """Grant a plan, replacing whatever was granted before.

        An update rather than a second row, which the unique constraint
        would refuse anyway -- and which is the honest shape: a workspace
        has one granted plan, and changing it is changing it rather than
        adding a second that outranks the first by accident of ordering.
        """
        existing = self.get_for_workspace(workspace_id)

        if existing is None:
            override = PlanOverride(
                workspace_id=workspace_id,
                plan=plan,
                reason=reason,
                granted_by_user_id=granted_by_user_id,
                expires_at=expires_at,
            )
            self._session.add(override)
        else:
            override = existing
            override.plan = plan
            override.reason = reason
            override.granted_by_user_id = granted_by_user_id
            override.expires_at = expires_at

        self._session.flush()

        return override

    def delete(self, override: PlanOverride) -> None:
        """Remove a grant, so the provider's word applies again.

        Deleted rather than marked, unlike almost everything else here.
        An override is a live entitlement and not a record: what happened
        is in `admin_audit_logs`, with who granted it, why, and who took
        it away -- and that outlives the workspace, which this row does
        not.
        """
        self._session.delete(override)
        self._session.flush()

    def list_all(self) -> Sequence[PlanOverride]:
        """Every override on the platform, newest first.

        The screen that answers "who is not paying us, and why did we
        agree to that" -- which is a question worth being able to ask
        without a database client.
        """
        return self._session.scalars(
            select(PlanOverride).order_by(
                PlanOverride.created_at.desc(),
                PlanOverride.id,
            )
        ).all()
