from fastapi import FastAPI

from app.api import users

app = FastAPI(title="orders-service")
app.include_router(users.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
