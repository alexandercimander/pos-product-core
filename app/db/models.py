from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Column, DateTime, Integer, String, Text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class SalesProcessTable(SQLModel, table=True):
    __tablename__ = "sales_processes"

    id: str = Field(sa_column=Column(String(64), primary_key=True))
    folder_id: str = Field(default="", sa_column=Column(String(64), index=True, nullable=False))
    folder_number: str = Field(default="", sa_column=Column(String(64), nullable=False))
    variant_number: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    source_process_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    channel_type: str = Field(default="", sa_column=Column(String(64), index=True, nullable=False))
    channel_instance_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    partner_connection_id: str | None = Field(default=None, sa_column=Column(String(64), index=True, nullable=True))
    release_bundle_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    flow_id: str = Field(default="", sa_column=Column(String(128), nullable=False))
    flow_version: str = Field(default="", sa_column=Column(String(32), nullable=False))
    status_engine_version: str = Field(default="v1", sa_column=Column(String(32), nullable=False))
    status: str = Field(default="ERFASST", sa_column=Column(String(64), index=True, nullable=False))
    intermediary_number: str = Field(default="", sa_column=Column(String(64), index=True, nullable=False))
    external_reference_number: str | None = Field(
        default=None,
        sa_column=Column(String(128), index=True, nullable=True),
    )
    canonical_state_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    case_file_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_archived: bool = Field(default=False)
    archived_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    archived_by_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    archived_by_id: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    archive_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    last_active_status: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SalesProcessHistoryTable(SQLModel, table=True):
    __tablename__ = "sales_process_history"

    id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))
    sales_process_id: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    from_status: str = Field(sa_column=Column(String(64), nullable=False))
    to_status: str = Field(sa_column=Column(String(64), nullable=False))
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class GeneratedDocumentTable(SQLModel, table=True):
    __tablename__ = "generated_documents"

    id: str = Field(sa_column=Column(String(128), primary_key=True))
    sales_process_id: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    document_kind: str = Field(sa_column=Column(String(32), index=True, nullable=False))
    mode: str = Field(default="GENERATED", sa_column=Column(String(32), nullable=False))
    variant: str = Field(sa_column=Column(String(64), nullable=False))
    version_number: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    mime_type: str = Field(default="application/pdf", sa_column=Column(String(128), nullable=False))
    file_name: str = Field(sa_column=Column(String(255), nullable=False))
    storage_provider: str = Field(default="filesystem", sa_column=Column(String(64), nullable=False))
    storage_reference: str = Field(sa_column=Column(String(512), nullable=False))
    checksum: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    size_bytes: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    generated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    required_documents_json: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    input_snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    source: str = Field(default="SYSTEM", sa_column=Column(String(32), nullable=False))
    submission_required: bool = Field(default=False)
    submission_allowed: bool = Field(default=True)
    submission_included: bool = Field(default=False)


class UploadedDocumentTable(SQLModel, table=True):
    __tablename__ = "uploaded_documents"

    id: str = Field(sa_column=Column(String(128), primary_key=True))
    sales_process_id: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    file_name: str = Field(sa_column=Column(String(255), nullable=False))
    mime_type: str = Field(default="application/octet-stream", sa_column=Column(String(128), nullable=False))
    storage_provider: str = Field(default="filesystem", sa_column=Column(String(64), nullable=False))
    storage_reference: str = Field(sa_column=Column(String(512), nullable=False))
    document_type: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    include_for_submission: bool = Field(default=False)
    checksum: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    size_bytes: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    uploaded_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProposalTable(SQLModel, table=True):
    __tablename__ = "proposals"

    id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))
    sales_process_id: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    generated_document_id: str = Field(sa_column=Column(String(128), nullable=False))
    proposal_type: str = Field(sa_column=Column(String(64), nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ApplicationTable(SQLModel, table=True):
    __tablename__ = "applications"

    id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))
    sales_process_id: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    generated_document_id: str = Field(sa_column=Column(String(128), nullable=False))
    application_type: str = Field(default="VVG", sa_column=Column(String(64), nullable=False))
    submitted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
