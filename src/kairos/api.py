from fastapi import FastAPI

from kairos.auth.google import router as auth_router
from kairos.routers.calendar import router as calendar_router
from kairos.routers.connections import router as connections_router
from kairos.routers.custom_metrics import router as custom_metrics_router
from kairos.routers.data import router as data_router
from kairos.routers.goals import router as goals_router
from kairos.routers.health import router as health_router
from kairos.routers.memory import router as memory_router
from kairos.routers.metrics import router as metrics_router
from kairos.routers.sync import router as sync_router

app = FastAPI(title="Kairos", version="0.1.0")
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sync_router)
# custom_metrics_router must be included before metrics_router -- metrics_router's
# GET /api/metrics/{metric_id} would otherwise swallow GET /api/metrics/custom
# (Starlette matches routes in registration order, both routers share the /api/metrics prefix)
app.include_router(custom_metrics_router)
app.include_router(metrics_router)
app.include_router(connections_router)
app.include_router(calendar_router)
app.include_router(data_router)
app.include_router(goals_router)
app.include_router(memory_router)
