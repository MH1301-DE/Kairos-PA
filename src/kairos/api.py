from fastapi import FastAPI

from kairos.auth.google import router as auth_router
from kairos.routers.health import router as health_router

app = FastAPI(title="Kairos", version="0.1.0")
app.include_router(health_router)
app.include_router(auth_router)
