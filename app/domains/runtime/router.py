from fastapi import APIRouter

from app.domains.runtime.schemas import RuntimeProjection
from app.domains.runtime.service import runtime_service
from app.domains.sales_process.service import sales_process_service


router = APIRouter()


@router.get("/sales-processes/{process_id}", response_model=RuntimeProjection)
def get_runtime_projection(process_id: str) -> RuntimeProjection:
    process = sales_process_service.get(process_id)
    return runtime_service.build_projection(process)

