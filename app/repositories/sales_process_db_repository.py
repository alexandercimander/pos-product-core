from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.db import create_db_and_tables
from app.db.models import (
    ApplicationTable,
    GeneratedDocumentTable,
    ProposalTable,
    SalesProcessHistoryTable,
    SalesProcessTable,
    UploadedDocumentTable,
)
from app.db.session import engine, reset_sqlite_database
from app.domains.sales_process.schemas import (
    DocumentSubmissionConfig,
    GeneratedDocumentRecord,
    SalesProcess,
    SalesProcessCaseFile,
    SalesProcessHistoryEntry,
    UserUploadedDocumentRecord,
)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class SalesProcessDbRepository:
    def __init__(self) -> None:
        create_db_and_tables()

    def load_all(self) -> dict[str, SalesProcess]:
        try:
            with Session(engine) as session:
                sales_process_rows = session.exec(select(SalesProcessTable)).all()
                if not sales_process_rows:
                    return {}

                history_rows = session.exec(select(SalesProcessHistoryTable)).all()
                generated_document_rows = session.exec(select(GeneratedDocumentTable)).all()
                uploaded_document_rows = session.exec(select(UploadedDocumentTable)).all()
        except OperationalError:
            reset_sqlite_database()
            create_db_and_tables()
            return {}

        history_by_process: dict[str, list[SalesProcessHistoryEntry]] = {}
        for row in history_rows:
            history_by_process.setdefault(row.sales_process_id, []).append(
                SalesProcessHistoryEntry(
                    event=row.event_type,
                    from_status=row.from_status,
                    to_status=row.to_status,
                    changed_at=_to_iso(row.created_at) or "",
                    metadata=row.payload_json,
                )
            )

        documents_by_process: dict[str, list[GeneratedDocumentRecord]] = {}
        for row in generated_document_rows:
            documents_by_process.setdefault(row.sales_process_id, []).append(
                GeneratedDocumentRecord(
                    id=row.id,
                    document_kind=row.document_kind,  # type: ignore[arg-type]
                    mode=row.mode,  # type: ignore[arg-type]
                    variant=row.variant,
                    version_number=row.version_number,
                    file_name=row.file_name,
                    mime_type=row.mime_type,
                    generated_at=_to_iso(row.generated_at) or "",
                    storage_reference=row.storage_reference,
                    summary=row.summary_json,
                    required_documents=row.required_documents_json,
                    input_snapshot=row.input_snapshot_json,
                    source=row.source,  # type: ignore[arg-type]
                    submission=DocumentSubmissionConfig(
                        required=row.submission_required,
                        allowed=row.submission_allowed,
                        included=row.submission_included,
                    ),
                )
            )

        uploads_by_process: dict[str, list[UserUploadedDocumentRecord]] = {}
        for row in uploaded_document_rows:
            uploads_by_process.setdefault(row.sales_process_id, []).append(
                UserUploadedDocumentRecord(
                    id=row.id,
                    file_name=row.file_name,
                    mime_type=row.mime_type,
                    uploaded_at=_to_iso(row.uploaded_at) or "",
                    storage_reference=row.storage_reference,
                    document_type=row.document_type,  # type: ignore[arg-type]
                    include_for_submission=row.include_for_submission,
                )
            )

        store: dict[str, SalesProcess] = {}
        for row in sales_process_rows:
            store[row.id] = SalesProcess(
                id=row.id,
                flow_id=row.flow_id,
                flow_version=row.flow_version,
                status_engine_version=row.status_engine_version,
                status=row.status,
                created_at=_to_iso(row.created_at) or "",
                updated_at=_to_iso(row.updated_at) or "",
                folder_id=row.folder_id,
                folder_number=row.folder_number,
                variant_number=row.variant_number,
                source_process_id=row.source_process_id,
                intermediary_number=row.intermediary_number,
                is_archived=row.is_archived,
                archived_at=_to_iso(row.archived_at),
                archived_by_type=row.archived_by_type,  # type: ignore[arg-type]
                archived_by_id=row.archived_by_id,
                archive_reason=row.archive_reason,
                last_active_status=row.last_active_status,
                canonical_state=row.canonical_state_json,
                history=history_by_process.get(row.id, []),
                generated_documents=documents_by_process.get(row.id, []),
                uploaded_documents=uploads_by_process.get(row.id, []),
                case_file=SalesProcessCaseFile.model_validate(row.case_file_json),
            )
        return store

    def replace_all(self, store: dict[str, SalesProcess], document_storage_provider: str) -> None:
        with Session(engine) as session:
            session.exec(delete(ApplicationTable))
            session.exec(delete(ProposalTable))
            session.exec(delete(UploadedDocumentTable))
            session.exec(delete(GeneratedDocumentTable))
            session.exec(delete(SalesProcessHistoryTable))
            session.exec(delete(SalesProcessTable))

            for process in store.values():
                external_reference_number = str(
                    process.canonical_state.get("externalApplicationNumber", "") or ""
                ) or None
                channel_type = str(process.canonical_state.get("inputChannel", "") or "")

                session.add(
                    SalesProcessTable(
                        id=process.id,
                        folder_id=process.folder_id,
                        folder_number=process.folder_number,
                        variant_number=process.variant_number,
                        source_process_id=process.source_process_id,
                        channel_type=channel_type,
                        channel_instance_id=None,
                        partner_connection_id=None,
                        release_bundle_id=None,
                        flow_id=process.flow_id,
                        flow_version=process.flow_version,
                        status_engine_version=process.status_engine_version,
                        status=process.status,
                        intermediary_number=process.intermediary_number,
                        external_reference_number=external_reference_number,
                        canonical_state_json=process.canonical_state,
                        case_file_json=process.case_file.model_dump(mode="json"),
                        is_archived=process.is_archived,
                        archived_at=_parse_timestamp(process.archived_at),
                        archived_by_type=process.archived_by_type,
                        archived_by_id=process.archived_by_id,
                        archive_reason=process.archive_reason,
                        last_active_status=process.last_active_status,
                        created_at=_parse_timestamp(process.created_at) or datetime.now(UTC),
                        updated_at=_parse_timestamp(process.updated_at) or datetime.now(UTC),
                    )
                )

                for entry in process.history:
                    session.add(
                        SalesProcessHistoryTable(
                            sales_process_id=process.id,
                            event_type=entry.event,
                            from_status=entry.from_status,
                            to_status=entry.to_status,
                            payload_json=entry.metadata,
                            created_at=_parse_timestamp(entry.changed_at) or datetime.now(UTC),
                        )
                    )

                for document in process.generated_documents:
                    session.add(
                        GeneratedDocumentTable(
                            id=document.id,
                            sales_process_id=process.id,
                            document_kind=document.document_kind,
                            mode=document.mode,
                            variant=document.variant,
                            version_number=document.version_number,
                            mime_type=document.mime_type,
                            file_name=document.file_name,
                            storage_provider=document_storage_provider,
                            storage_reference=document.storage_reference,
                            checksum=None,
                            size_bytes=None,
                            generated_at=_parse_timestamp(document.generated_at) or datetime.now(UTC),
                            summary_json=document.summary,
                            required_documents_json=document.required_documents,
                            input_snapshot_json=document.input_snapshot,
                            source=document.source,
                            submission_required=document.submission.required,
                            submission_allowed=document.submission.allowed,
                            submission_included=document.submission.included,
                        )
                    )

                    if document.document_kind == "PROPOSAL":
                        session.add(
                            ProposalTable(
                                sales_process_id=process.id,
                                generated_document_id=document.id,
                                proposal_type=document.variant,
                                created_at=_parse_timestamp(document.generated_at) or datetime.now(UTC),
                            )
                        )
                    if document.document_kind == "APPLICATION":
                        session.add(
                            ApplicationTable(
                                sales_process_id=process.id,
                                generated_document_id=document.id,
                                application_type=document.variant,
                                submitted_at=_parse_timestamp(process.case_file.submitted_at),
                                created_at=_parse_timestamp(document.generated_at) or datetime.now(UTC),
                            )
                        )

                for document in process.uploaded_documents:
                    session.add(
                        UploadedDocumentTable(
                            id=document.id,
                            sales_process_id=process.id,
                            file_name=document.file_name,
                            mime_type=document.mime_type,
                            storage_provider=document_storage_provider,
                            storage_reference=document.storage_reference,
                            document_type=document.document_type,
                            include_for_submission=document.include_for_submission,
                            checksum=None,
                            size_bytes=None,
                            uploaded_at=_parse_timestamp(document.uploaded_at) or datetime.now(UTC),
                        )
                    )

            session.commit()
