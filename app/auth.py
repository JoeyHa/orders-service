import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import settings


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")
