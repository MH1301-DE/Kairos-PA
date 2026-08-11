from fastapi import FastAPI

from kairos.auth.google import router as auth_router
from kairos.routers.connections import router as connections_router
from kairos.routers.health import router as health_router
from kairos.routers.metrics import router as metrics_router
from kairos.routers.sync import router as sync_router

app = FastAPI(title="Kairos", version="0.1.0")
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(metrics_router)
app.include_router(connections_router)
