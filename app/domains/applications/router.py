from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.domains.sales_process.schemas import (
    ApplicationDocumentRequest,
    GeneratedDocumentResponse,
)
from app.domains.sales_process.service import sales_process_service


router = APIRouter()


class CreateApplicationRequest(ApplicationDocumentRequest):
    sales_process_id: str


@router.post("", response_model=GeneratedDocumentResponse)
def create_application(request: CreateApplicationRequest) -> GeneratedDocumentResponse:
    return sales_process_service.generate_application(
        request.sales_process_id,
        request,
    )


@router.get("/{application_id}", response_model=GeneratedDocumentResponse)
def get_application(application_id: str) -> GeneratedDocumentResponse:
    return sales_process_service.get_document_response(application_id, "APPLICATION")


@router.get("/{application_id}/download")
def download_application(application_id: str) -> FileResponse:
    target = sales_process_service.download_document_by_id(application_id, "APPLICATION")
    return FileResponse(path=target, media_type="application/pdf", filename=target.name)
