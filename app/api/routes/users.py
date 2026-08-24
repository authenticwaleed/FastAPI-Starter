from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.user import UserCreate, UserPage, UserRead, UserUpdate
from app.services.user_service import (
    EmailAlreadyExistsError,
    UserNotFoundError,
    UserServiceDep,
)


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
def list_users(
    service: UserServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    # Capped so a client cannot ask for the whole table in one request.
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    users, total = service.list_users(page=page, page_size=page_size)

    return UserPage(
        items=users,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}")
def get_user(
    user_id: int,
    service: UserServiceDep,
) -> UserRead:
    try:
        return service.get_user(user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from None


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    service: UserServiceDep,
) -> UserRead:
    try:
        return service.update_user(user_id, payload)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from None
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    service: UserServiceDep,
) -> None:
    try:
        service.delete_user(user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from None
