from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.auth import require_api_key
from app.db import SessionDep
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    name: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    created_at: datetime


@router.post("", status_code=201, response_model=UserOut, dependencies=[Depends(require_api_key)])
async def create_user(body: UserIn, session: SessionDep) -> User:
    user = User(email=body.email.lower(), name=body.name)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already exists") from None
    await session.refresh(user)  # load server-side created_at
    return user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: SessionDep) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user
