import uuid

from fastapi import APIRouter, status

from app.api.dependencies.auth import AuthenticatedDep, CurrentUserDep
from app.api.errors import (
    BAD_REQUEST,
    CONFLICT,
    FORBIDDEN,
    OWNERSHIP_CONFLICT,
    SESSION_NOT_FOUND,
    UNAUTHORISED,
)
from app.models.user_session import UserSession
from app.schemas.account import AccountUpdate, PasswordChange
from app.schemas.session import SessionRead
from app.schemas.user import UserRead
from app.services.account_service import AccountServiceDep
from app.services.session_service import SessionServiceDep

router = APIRouter(
    prefix="/account",
    tags=["account"],
)


# Not one of these routes takes a user id in the path, which is the point of
# the phase rather than an omission: the only account they can reach is the
# one CurrentUserDep resolved from the token, so there is no id for a caller
# to substitute and no ownership check for anyone to forget.
#
# The response model is UserRead rather than an account-shaped copy of it.
# One schema is one guarantee that neither a password nor its hash can be
# serialised, where two could drift apart.
#
# Sync, like every other route that reaches the database.
@router.get("", responses={**UNAUTHORISED, **FORBIDDEN})
def read_account(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("", responses={**UNAUTHORISED, **FORBIDDEN, **CONFLICT})
def update_account(
    payload: AccountUpdate,
    user: CurrentUserDep,
    service: AccountServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.update(user, payload))


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORISED, **FORBIDDEN, **BAD_REQUEST},
)
def change_password(
    payload: PasswordChange,
    authenticated: AuthenticatedDep,
    service: AccountServiceDep,
) -> None:
    """Nothing is returned. The new password is not an API response.

    Every other session is signed out, and this one is not. Somebody
    changing their password because they think it was learned wants the
    other device to stop working, and does not want to be thrown out of
    the screen they are standing in front of.
    """
    service.change_password(
        authenticated.user,
        payload,
        keep_session=authenticated.session,
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORISED, **FORBIDDEN, **OWNERSHIP_CONFLICT},
)
def delete_account(
    user: CurrentUserDep,
    service: AccountServiceDep,
) -> None:
    service.delete(user)


# --- sessions -------------------------------------------------------------
#
# Under /account rather than under /auth, because these are not part of
# authenticating: they are the account looking at itself. The same rule as
# the routes above applies -- the only sessions reachable here are the ones
# belonging to the token that arrived, and `SessionService` refuses an id
# that names anybody else's.


def _read(session: UserSession, *, current_id: uuid.UUID) -> SessionRead:
    return SessionRead(
        id=session.id,
        created_at=session.created_at,
        last_used_at=session.last_used_at,
        expires_at=session.expires_at,
        user_agent=session.user_agent,
        ip_address=session.ip_address,
        current=session.id == current_id,
    )


@router.get("/sessions", responses={**UNAUTHORISED, **FORBIDDEN})
def list_sessions(
    authenticated: AuthenticatedDep,
    service: SessionServiceDep,
) -> list[SessionRead]:
    """Where this account is currently signed in.

    Live sessions only. A list including the ones that already ended
    would be a history, and the question being asked is "what can get
    into my account right now?".
    """
    return [
        _read(session, current_id=authenticated.session.id)
        for session in service.list_for(authenticated.user)
    ]


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORISED, **FORBIDDEN},
)
def revoke_all_sessions(
    authenticated: AuthenticatedDep,
    service: SessionServiceDep,
) -> None:
    """Sign out everywhere, this device included.

    The access token in hand keeps working until it expires, which is
    minutes. Everything that could outlive that -- every refresh chain,
    on every device -- is gone by the time this returns.
    """
    service.revoke_all(authenticated.user)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORISED, **FORBIDDEN, **SESSION_NOT_FOUND},
)
def revoke_session(
    session_id: uuid.UUID,
    authenticated: AuthenticatedDep,
    service: SessionServiceDep,
) -> None:
    service.revoke(authenticated.user, session_id)
