from fastapi import FastAPI

app = FastAPI(title="orders-service")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
