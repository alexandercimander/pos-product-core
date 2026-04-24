from fastapi import APIRouter

from app.domains.applications.router import router as applications_router
from app.domains.health_questions.router import router as health_questions_router
from app.domains.proposals.router import router as proposals_router
from app.domains.runtime.router import router as runtime_router
from app.domains.sales_process.router import router as sales_process_router
from app.domains.status_engine.router import router as status_engine_router
from app.domains.tariffs.router import router as tariffs_router


api_router = APIRouter()
api_router.include_router(applications_router, prefix="/applications", tags=["core-applications"])
api_router.include_router(
    health_questions_router,
    prefix="/health-questions",
    tags=["core-health-questions"],
)
api_router.include_router(proposals_router, prefix="/proposals", tags=["core-proposals"])
api_router.include_router(runtime_router, prefix="/runtime", tags=["core-runtime"])
api_router.include_router(
    sales_process_router,
    prefix="/sales-processes",
    tags=["core-sales-processes"],
)
api_router.include_router(
    status_engine_router,
    prefix="/status-engine",
    tags=["core-status-engine"],
)
api_router.include_router(tariffs_router, prefix="/tariffs", tags=["core-tariffs"])
