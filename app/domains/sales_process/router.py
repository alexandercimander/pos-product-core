from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.domains.sales_process.schemas import (
    ArchiveSalesProcessRequest,
    CreateVariantRequest,
    CreateSalesProcessRequest,
    FinalizeSalesProcessRequest,
    NumberValidationResponse,
    RestoreSalesProcessRequest,
    SalesProcessListResponse,
    SalesProcess,
    UploadSalesProcessDocumentRequest,
    UpdateSalesProcessRequest,
)
from app.domains.sales_process.service import sales_process_service


router = APIRouter()


@router.post("", response_model=SalesProcess)
def create_sales_process(request: CreateSalesProcessRequest) -> SalesProcess:
    return sales_process_service.create(request)


@router.get("", response_model=list[SalesProcess])
def list_sales_processes() -> list[SalesProcess]:
    return sales_process_service.list()


@router.get("/query", response_model=SalesProcessListResponse)
def query_sales_processes(
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "createdAt",
    sort_dir: str = "desc",
    submission_range: str = "",
    intermediary_number: str = "",
    folder_number: str = "",
    process_number: str = "",
    policy_holder: str = "",
    status: str = "",
    input_channel: str = "",
    external_reference_number: str = "",
    include_archived: bool = False,
    status_bucket: str = "",
) -> SalesProcessListResponse:
    return sales_process_service.list_page(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        submission_range=submission_range,
        intermediary_number=intermediary_number,
        folder_number=folder_number,
        process_number=process_number,
        policy_holder=policy_holder,
        status=status,
        input_channel=input_channel,
        external_reference_number=external_reference_number,
        include_archived=include_archived,
        status_bucket=status_bucket,
    )


@router.delete("/folders/{folder_id}")
def delete_sales_process_folder(folder_id: str) -> dict[str, int | str]:
    deleted = sales_process_service.delete_folder(folder_id)
    return {"status": "deleted", "deleted_count": deleted}


@router.post("/folders/{folder_id}/archive")
def archive_sales_process_folder(
    folder_id: str,
    request: ArchiveSalesProcessRequest,
) -> dict[str, int | str]:
    archived = sales_process_service.archive_folder(folder_id, request)
    return {"status": "archived", "archived_count": archived}


@router.get("/numbering/validate", response_model=NumberValidationResponse)
def validate_sales_process_number(
    number: str,
    kind: str = "SALES_PROCESS",
) -> NumberValidationResponse:
    normalized_kind = "FOLDER" if kind.upper() == "FOLDER" else "SALES_PROCESS"
    return sales_process_service.validate_number(number, normalized_kind)


@router.get("/{process_id}", response_model=SalesProcess)
def get_sales_process(process_id: str) -> SalesProcess:
    return sales_process_service.get(process_id)


@router.put("/{process_id}", response_model=SalesProcess)
def update_sales_process(
    process_id: str,
    request: UpdateSalesProcessRequest,
) -> SalesProcess:
    return sales_process_service.update(process_id, request)


@router.delete("/{process_id}")
def delete_sales_process(process_id: str) -> dict[str, str]:
    sales_process_service.delete(process_id)
    return {"status": "deleted"}


@router.post("/{process_id}/archive", response_model=SalesProcess)
def archive_sales_process(
    process_id: str,
    request: ArchiveSalesProcessRequest,
) -> SalesProcess:
    return sales_process_service.archive(process_id, request)


@router.post("/{process_id}/restore", response_model=SalesProcess)
def restore_sales_process(
    process_id: str,
    request: RestoreSalesProcessRequest,
) -> SalesProcess:
    return sales_process_service.restore(process_id, request)


@router.post("/{process_id}/variants", response_model=SalesProcess)
def create_variant(
    process_id: str,
    request: CreateVariantRequest,
) -> SalesProcess:
    return sales_process_service.create_variant(process_id, request)


@router.post("/{process_id}/finalize", response_model=SalesProcess)
def finalize_sales_process(
    process_id: str,
    request: FinalizeSalesProcessRequest,
) -> SalesProcess:
    return sales_process_service.finalize(process_id, request)


@router.post("/{process_id}/uploads", response_model=SalesProcess)
def upload_sales_process_document(
    process_id: str,
    request: UploadSalesProcessDocumentRequest,
) -> SalesProcess:
    return sales_process_service.upload_case_file_document(process_id, request)


@router.get("/{process_id}/uploads/{upload_id}/download")
def download_sales_process_upload(
    process_id: str,
    upload_id: str,
) -> FileResponse:
    target, mime_type = sales_process_service.download_uploaded_document(process_id, upload_id)
    return FileResponse(path=target, media_type=mime_type, filename=target.name)
