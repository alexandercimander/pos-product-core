from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SalesProcessHistoryEntry(BaseModel):
    event: str
    from_status: str
    to_status: str
    changed_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSubmissionConfig(BaseModel):
    required: bool = False
    allowed: bool = True
    included: bool = False


class GeneratedDocumentRecord(BaseModel):
    id: str
    document_kind: Literal["PROPOSAL", "APPLICATION"]
    mode: Literal["STATIC", "GENERATED", "EXTERNAL"]
    variant: str
    version_number: int
    file_name: str
    mime_type: str = "application/pdf"
    generated_at: str
    storage_reference: str
    summary: dict[str, Any] = Field(default_factory=dict)
    required_documents: list[str] = Field(default_factory=list)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    source: Literal["SYSTEM", "USER", "RULES"] = "SYSTEM"
    submission: DocumentSubmissionConfig = Field(default_factory=DocumentSubmissionConfig)


class UserUploadedDocumentRecord(BaseModel):
    id: str
    file_name: str
    mime_type: str = "application/octet-stream"
    uploaded_at: str
    storage_reference: str
    classification: Literal["USER_UPLOADED"] = "USER_UPLOADED"
    source: Literal["USER"] = "USER"
    document_type: Literal["GENERAL_ATTACHMENT", "SIGNED_APPLICATION", "MEDICAL_ATTACHMENT"] = (
        "GENERAL_ATTACHMENT"
    )
    include_for_submission: bool = False


class SalesProcessCaseFile(BaseModel):
    status: Literal["OFFEN", "ABGESCHLOSSEN", "EINGEREICHT"] = "OFFEN"
    finalized_at: str | None = None
    snapshot_version: int = 1
    read_only_snapshot: dict[str, Any] = Field(default_factory=dict)
    visible_document_ids: list[str] = Field(default_factory=list)
    generated_document_ids: list[str] = Field(default_factory=list)
    supporting_document_ids: list[str] = Field(default_factory=list)
    uploaded_document_ids: list[str] = Field(default_factory=list)
    signature_required: bool = False
    signature_status: Literal[
        "NICHT_ERFORDERLICH",
        "OFFEN",
        "HOCHGELADEN",
        "EXTERN_GESTARTET",
        "ABGESCHLOSSEN",
    ] = "NICHT_ERFORDERLICH"
    submission_ready: bool = False
    submitted_at: str | None = None
    policy_issued_at: str | None = None
    policy_number: str | None = None


class SalesProcess(BaseModel):
    id: str
    flow_id: str
    flow_version: str
    status_engine_version: str = "v1"
    status: str = "ERFASST"
    created_at: str = ""
    updated_at: str = ""
    folder_id: str = ""
    folder_number: str = ""
    variant_number: int = 1
    source_process_id: str | None = None
    intermediary_number: str = ""
    is_archived: bool = False
    archived_at: str | None = None
    archived_by_type: Literal["SYSTEM", "USER"] | None = None
    archived_by_id: str | None = None
    archive_reason: str | None = None
    last_active_status: str | None = None
    canonical_state: dict[str, Any] = Field(default_factory=dict)
    history: list[SalesProcessHistoryEntry] = Field(default_factory=list)
    generated_documents: list[GeneratedDocumentRecord] = Field(default_factory=list)
    uploaded_documents: list[UserUploadedDocumentRecord] = Field(default_factory=list)
    case_file: SalesProcessCaseFile = Field(default_factory=SalesProcessCaseFile)


class CreateSalesProcessRequest(BaseModel):
    id: str | None = None
    flow_id: str
    flow_version: str
    status_engine_version: str = "v1"
    intermediary_number: str = ""
    canonical_state: dict[str, Any] = Field(default_factory=dict)


class UpdateSalesProcessRequest(BaseModel):
    status: str | None = None
    canonical_state: dict[str, Any] | None = None
    transition_event: str | None = None


class FinalizeSalesProcessRequest(BaseModel):
    visible_document_ids: list[str] = Field(default_factory=list)
    supporting_document_ids: list[str] = Field(default_factory=list)


class UploadSalesProcessDocumentRequest(BaseModel):
    file_name: str
    mime_type: str = "application/octet-stream"
    content_base64: str
    document_type: Literal["GENERAL_ATTACHMENT", "SIGNED_APPLICATION", "MEDICAL_ATTACHMENT"] = (
        "GENERAL_ATTACHMENT"
    )
    include_for_submission: bool = False


class ArchiveSalesProcessRequest(BaseModel):
    archived_by_type: Literal["SYSTEM", "USER"] = "USER"
    archived_by_id: str = ""
    reason: str | None = None


class RestoreSalesProcessRequest(BaseModel):
    restored_by_type: Literal["SYSTEM", "USER"] = "USER"
    restored_by_id: str = ""


class ProposalDocumentRequest(BaseModel):
    proposal_type: Literal["STANDARD", "VVG"]


class ApplicationDocumentRequest(BaseModel):
    application_type: Literal["VVG"] = "VVG"


class GeneratedDocumentResponse(BaseModel):
    document_id: str
    sales_process_id: str
    document_kind: Literal["PROPOSAL", "APPLICATION"]
    mode: Literal["STATIC", "GENERATED", "EXTERNAL"]
    variant: str
    version_number: int
    file_name: str
    mime_type: str = "application/pdf"
    generated_at: str
    status: str
    storage_reference: str
    required_documents: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class CreateVariantRequest(BaseModel):
    intermediary_number: str | None = None


class NumberValidationResponse(BaseModel):
    number: str
    kind: Literal["SALES_PROCESS", "FOLDER"]
    valid_format: bool
    valid_checksum: bool
    exists: bool
    prefix: str | None = None
    uniqueness_id: str | None = None
    version: int | None = None
    check_digit: int | None = None
    expected_check_digit: int | None = None
    errors: list[str] = Field(default_factory=list)


class SalesProcessListItem(BaseModel):
    id: str
    folder_id: str
    folder_number: str
    created_at: str
    updated_at: str
    variant_number: int
    intermediary_number: str
    status: str
    input_channel: str = ""
    external_reference_number: str = ""
    policy_holder_first_name: str = ""
    policy_holder_last_name: str = ""
    submitted_at: str | None = None
    is_archived: bool = False
    archived_at: str | None = None
    archived_by_type: Literal["SYSTEM", "USER"] | None = None
    archived_by_id: str | None = None
    last_active_status: str | None = None


class SalesProcessListAggregates(BaseModel):
    total_processes: int = 0
    total_folders: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    input_channel_counts: dict[str, int] = Field(default_factory=dict)


class SalesProcessListResponse(BaseModel):
    items: list[SalesProcessListItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25
    total_pages: int = 0
    has_prev: bool = False
    has_next: bool = False
    aggregates: SalesProcessListAggregates = Field(default_factory=SalesProcessListAggregates)
