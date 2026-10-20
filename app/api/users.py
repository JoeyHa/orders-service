from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.auth import require_api_key
from app.db import SessionDep
from app.models import INT4_MAX, User

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s\x00]+@[^@\s\x00]+$")
    name: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00]+$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    created_at: datetime


@router.post("", status_code=201, response_model=UserOut, dependencies=[Depends(require_api_key)])
async def create_user(body: UserIn, session: SessionDep) -> User:
    """Create a user. The email is stored lowercased; an email already in use returns 409."""
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
async def get_user(user_id: Annotated[int, Path(ge=1, le=INT4_MAX)], session: SessionDep) -> User:
    """Fetch one user by id; 404 if there is none, 422 if the id is outside 1..2**31-1."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user
