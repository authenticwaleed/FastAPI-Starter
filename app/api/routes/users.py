from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.user import UserCreate, UserRead
from app.services.user_service import UserService, get_user_service


router = APIRouter(
    prefix="/users",
    tags=["users"],
)

UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    service: UserServiceDep,
) -> UserRead:
    return service.create_user(payload)


@router.get("")
async def list_users(service: UserServiceDep) -> list[UserRead]:
    return service.list_users()


@router.get("/{user_id}")
async def get_user(
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
