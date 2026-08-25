from fastapi import APIRouter, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.errors import BAD_REQUEST, CONFLICT, FORBIDDEN, UNAUTHORISED
from app.schemas.account import AccountUpdate, PasswordChange
from app.schemas.user import UserRead
from app.services.account_service import AccountServiceDep

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
    user: CurrentUserDep,
    service: AccountServiceDep,
) -> None:
    """Nothing is returned. The new password is not an API response."""
    service.change_password(user, payload)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORISED, **FORBIDDEN},
)
def delete_account(
    user: CurrentUserDep,
    service: AccountServiceDep,
) -> None:
    service.delete(user)
