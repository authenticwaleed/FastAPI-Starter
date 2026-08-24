from fastapi import APIRouter, HTTPException, status

from app.schemas.user import UserCreate, UserRead
from app.services.user_service import EmailAlreadyExistsError, UserServiceDep


router = APIRouter(
    prefix="/users",
    tags=["users"],
)


# These handlers are sync on purpose. The session is a blocking, sync
# SQLAlchemy session, so FastAPI runs them in a threadpool instead of letting
# a slow query stall the event loop for every other request.
@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    service: UserServiceDep,
) -> UserRead:
    try:
        return service.create_user(payload)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None


@router.get("")
def list_users(service: UserServiceDep) -> list[UserRead]:
    return service.list_users()


@router.get("/{user_id}")
def get_user(
    user_id: int,
    service: UserServiceDep,
) -> UserRead:
    user = service.get_user(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user
