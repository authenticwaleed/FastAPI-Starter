from fastapi import APIRouter, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.errors import CONFLICT, FORBIDDEN, UNAUTHORISED
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthServiceDep

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


# Sync for the same reason as the user routes: the session is blocking, so
# an async handler would stall the event loop while a query runs.
@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses=CONFLICT,
)
def register(
    payload: UserCreate,
    service: AuthServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.register(payload))


@router.post("/login", responses={**UNAUTHORISED, **FORBIDDEN})
def login(
    credentials: LoginRequest,
    service: AuthServiceDep,
) -> Token:
    return service.login(credentials)


@router.get("/me", responses={**UNAUTHORISED, **FORBIDDEN})
def read_current_user(user: CurrentUserDep) -> UserRead:
    """The protected endpoint. The dependency has already done the work."""
    return UserRead.model_validate(user)
