from fastapi import FastAPI

from chess_coach.api.routes.system import router as system_router

app = FastAPI(
    title="Chess Coach API",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(system_router)
