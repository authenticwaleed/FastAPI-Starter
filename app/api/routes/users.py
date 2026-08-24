from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.errors import CONFLICT, NOT_FOUND
from app.schemas.user import UserCreate, UserPage, UserRead, UserUpdate
from app.services.user_service import UserServiceDep

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


# These handlers are sync on purpose. The session is a blocking, sync
# SQLAlchemy session, so FastAPI runs them in a threadpool instead of letting
# a slow query stall the event loop for every other request.
#
# None of them catch anything. A service raises a domain error and the
# handlers registered in app/api/errors.py turn it into a response, so what
# is left here is only the HTTP shape of each operation.
@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
def create_user(
    payload: UserCreate,
    service: UserServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.create_user(payload))


@router.get("")
def list_users(
    service: UserServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    # Capped so a client cannot ask for the whole table in one request.
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    users, total = service.list_users(page=page, page_size=page_size)

    return UserPage(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", responses=NOT_FOUND)
def get_user(
    user_id: int,
    service: UserServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.get_user(user_id))


@router.patch("/{user_id}", responses={**NOT_FOUND, **CONFLICT})
def update_user(
    user_id: int,
    payload: UserUpdate,
    service: UserServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.update_user(user_id, payload))


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
)
def delete_user(
    user_id: int,
    service: UserServiceDep,
) -> None:
    service.delete_user(user_id)
