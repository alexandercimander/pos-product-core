from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.domains.sales_process.schemas import GeneratedDocumentResponse, ProposalDocumentRequest
from app.domains.sales_process.service import sales_process_service


router = APIRouter()


class CreateProposalRequest(ProposalDocumentRequest):
    sales_process_id: str


@router.post("", response_model=GeneratedDocumentResponse)
def create_proposal(request: CreateProposalRequest) -> GeneratedDocumentResponse:
    return sales_process_service.generate_proposal(
        request.sales_process_id,
        request,
    )


@router.get("/{proposal_id}", response_model=GeneratedDocumentResponse)
def get_proposal(proposal_id: str) -> GeneratedDocumentResponse:
    return sales_process_service.get_document_response(proposal_id, "PROPOSAL")


@router.get("/{proposal_id}/download")
def download_proposal(proposal_id: str) -> FileResponse:
    target = sales_process_service.download_document_by_id(proposal_id, "PROPOSAL")
    return FileResponse(path=target, media_type="application/pdf", filename=target.name)
