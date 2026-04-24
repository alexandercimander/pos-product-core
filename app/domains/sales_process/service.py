from __future__ import annotations

from datetime import datetime, UTC, timedelta
from copy import deepcopy
import base64
from pathlib import Path
import secrets
from fastapi import HTTPException

from app.core.bindings import resolve_binding
from app.core.config import settings
from app.core.external_http import post_json
from app.domains.document_output.service import document_output_service
from app.domains.sales_process.schemas import (
    ArchiveSalesProcessRequest,
    ApplicationDocumentRequest,
    CreateVariantRequest,
    CreateSalesProcessRequest,
    DocumentSubmissionConfig,
    FinalizeSalesProcessRequest,
    GeneratedDocumentResponse,
    GeneratedDocumentRecord,
    NumberValidationResponse,
    ProposalDocumentRequest,
    RestoreSalesProcessRequest,
    SalesProcessListAggregates,
    SalesProcessListItem,
    SalesProcessListResponse,
    SalesProcessCaseFile,
    SalesProcess,
    SalesProcessHistoryEntry,
    UploadSalesProcessDocumentRequest,
    UpdateSalesProcessRequest,
    UserUploadedDocumentRecord,
)
from app.domains.status_engine.service import status_engine_service
from app.domains.tariffs.schemas import TariffCalculationRequest
from app.domains.tariffs.calculation import calculate_tariff_payable_price
from app.domains.tariffs.service import tariff_service
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.json_store_repository import JsonStoreRepository


class SalesProcessService:
    def __init__(self) -> None:
        self.repository = JsonStoreRepository(settings.storage_root)
        self.artifact_repository = ArtifactRepository(settings.artifacts_root)
        payload = self.repository.read("sales_processes.json")
        self._store: dict[str, SalesProcess] = {}
        self._search_index: dict[str, str] = {}
        self._status_index: dict[str, set[str]] = {}
        self._input_channel_index: dict[str, set[str]] = {}
        self._retention_policy_cache: dict[tuple[str, str], dict[str, object]] = {}
        for process_id, process in payload.items():
            self._store[process_id] = self._normalize_loaded_process(
                SalesProcess.model_validate(process)
            )
        self._persist()

    def _persist(self) -> None:
        self.repository.write(
            "sales_processes.json",
            {key: value.model_dump(mode="json") for key, value in self._store.items()},
        )
        self._rebuild_indices()

    def _extract_policy_holder_name(self, process: SalesProcess) -> tuple[str, str]:
        partners = process.canonical_state.get("partners")
        if not isinstance(partners, list):
            return "", ""
        for entry in partners:
            if not isinstance(entry, dict):
                continue
            roles = entry.get("roles")
            if not isinstance(roles, list) or "POLICY_HOLDER" not in roles:
                continue
            firstname = str(entry.get("firstname", "") or "")
            lastname = str(entry.get("lastname", "") or "")
            return firstname, lastname
        return "", ""

    def _to_list_item(self, process: SalesProcess) -> SalesProcessListItem:
        firstname, lastname = self._extract_policy_holder_name(process)
        return SalesProcessListItem(
            id=process.id,
            folder_id=process.folder_id,
            folder_number=process.folder_number,
            created_at=process.created_at,
            updated_at=process.updated_at,
            variant_number=process.variant_number,
            intermediary_number=process.intermediary_number,
            status=process.status,
            input_channel=str(process.canonical_state.get("inputChannel", "") or ""),
            external_reference_number=str(
                process.canonical_state.get("externalApplicationNumber", "") or ""
            ),
            policy_holder_first_name=firstname,
            policy_holder_last_name=lastname,
            submitted_at=process.case_file.submitted_at,
            is_archived=process.is_archived,
            archived_at=process.archived_at,
            archived_by_type=process.archived_by_type,
            archived_by_id=process.archived_by_id,
            last_active_status=process.last_active_status,
        )

    def _rebuild_indices(self) -> None:
        self._search_index = {}
        self._status_index = {}
        self._input_channel_index = {}
        for process in self._store.values():
            item = self._to_list_item(process)
            self._status_index.setdefault(item.status, set()).add(item.id)
            normalized_channel = item.input_channel.strip().lower()
            if normalized_channel:
                self._input_channel_index.setdefault(normalized_channel, set()).add(item.id)
            searchable = " ".join(
                [
                    item.id,
                    item.folder_number,
                    item.intermediary_number,
                    item.external_reference_number,
                    item.policy_holder_first_name,
                    item.policy_holder_last_name,
                    item.input_channel,
                    item.status,
                ]
            ).lower()
            self._search_index[item.id] = searchable

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _retention_threshold(self, rule: dict[str, object] | None) -> timedelta | None:
        if not isinstance(rule, dict):
            return None
        if not bool(rule.get("enabled", False)):
            return None
        value = int(rule.get("value", 0) or 0)
        if value <= 0:
            return None
        unit = str(rule.get("unit", "DAYS")).upper()
        if unit == "HOURS":
            return timedelta(hours=value)
        if unit == "WEEKS":
            return timedelta(weeks=value)
        if unit == "YEARS":
            return timedelta(days=365 * value)
        return timedelta(days=value)

    def _load_retention_policy(self, flow_id: str, flow_version: str) -> dict[str, object]:
        cache_key = (flow_id, flow_version)
        cached = self._retention_policy_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            payload = self.artifact_repository.read_json(
                "flows",
                flow_id,
                flow_version,
                "flow.json",
            )
        except FileNotFoundError:
            policy: dict[str, object] = {}
            self._retention_policy_cache[cache_key] = policy
            return policy
        journey_config = payload.get("journeyConfig", {})
        retention_policy = (
            journey_config.get("retentionPolicy", {}) if isinstance(journey_config, dict) else {}
        )
        policy = retention_policy if isinstance(retention_policy, dict) else {}
        self._retention_policy_cache[cache_key] = policy
        return policy

    def _archive_in_memory(
        self,
        process: SalesProcess,
        *,
        archived_by_type: str,
        archived_by_id: str,
        reason: str,
    ) -> SalesProcess:
        if process.is_archived:
            return process
        previous_status = process.status
        canonical_state = dict(process.canonical_state)
        canonical_state["status"] = "ARCHIVIERT"
        updated = process.model_copy(
            update={
                "updated_at": self._timestamp(),
                "status": "ARCHIVIERT",
                "canonical_state": canonical_state,
                "is_archived": True,
                "archived_at": self._timestamp(),
                "archived_by_type": archived_by_type,
                "archived_by_id": archived_by_id,
                "archive_reason": reason,
                "last_active_status": previous_status,
            }
        )
        return self._append_history(
            updated,
            event="ARCHIVE_SALES_PROCESS",
            from_status=previous_status,
            to_status="ARCHIVIERT",
            metadata={
                "archived_by_type": archived_by_type,
                "archived_by_id": archived_by_id,
                "reason": reason,
            },
        )

    def _apply_retention_policy(self) -> None:
        self._retention_policy_cache.clear()
        now = datetime.now(UTC)
        to_delete: list[str] = []
        changed = False
        for process_id, process in list(self._store.items()):
            policy = self._load_retention_policy(process.flow_id, process.flow_version)
            archive_threshold = self._retention_threshold(
                policy.get("autoArchiveInactive")
                if isinstance(policy, dict)
                else None
            )
            delete_threshold = self._retention_threshold(
                policy.get("autoDeleteArchived")
                if isinstance(policy, dict)
                else None
            )

            updated_at = self._parse_timestamp(process.updated_at) or self._parse_timestamp(process.created_at)
            if (
                not process.is_archived
                and archive_threshold is not None
                and updated_at is not None
                and now - updated_at >= archive_threshold
            ):
                self._store[process_id] = self._archive_in_memory(
                    process,
                    archived_by_type="SYSTEM",
                    archived_by_id="retention-engine",
                    reason="AUTO_INACTIVE_RETENTION",
                )
                changed = True
                process = self._store[process_id]

            archived_at = self._parse_timestamp(process.archived_at)
            if (
                process.is_archived
                and self._is_archived_application(process)
                and delete_threshold is not None
                and archived_at is not None
                and now - archived_at >= delete_threshold
            ):
                to_delete.append(process_id)

        if to_delete:
            for process_id in to_delete:
                self._store.pop(process_id, None)
            changed = True
        if changed:
            self._persist()

    def _is_archived_application(self, process: SalesProcess) -> bool:
        if process.case_file.submitted_at:
            return True
        if process.case_file.signature_status in {"HOCHGELADEN", "EXTERN_GESTARTET", "ABGESCHLOSSEN"}:
            return True
        if process.status in {"ANTRAG_ERSTELLT", "ANTRAG_EINGEREICHT", "IN_AKTE_UEBERFUEHRT"}:
            return True
        if process.last_active_status in {"ANTRAG_ERSTELLT", "ANTRAG_EINGEREICHT", "IN_AKTE_UEBERFUEHRT"}:
            return True
        return any(document.document_kind == "APPLICATION" for document in process.generated_documents)

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()

    def _date_token(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%d")

    def _normalize_prefix(self, prefix: str | None) -> str:
        normalized = "".join(character for character in (prefix or "").upper() if "A" <= character <= "Z")
        return normalized or "VV"

    def _derive_prefix_from_input_channel(self, input_channel: str | None) -> str:
        value = (input_channel or "").strip()
        if not value:
            return "VV"
        tokens = [
            "".join(character for character in token if character.isalnum())
            for token in value.replace("-", " ").split()
        ]
        initials = "".join(token[0] for token in tokens if token)
        if initials:
            return self._normalize_prefix(initials[:3])
        compact = "".join(character for character in value if character.isalnum())
        return self._normalize_prefix(compact[:3] if compact else "VV")

    def _normalize_status(self, status: str) -> str:
        normalized = str(status or "").strip().upper()
        if normalized == "CREATED":
            return "ERFASST"
        if normalized == "ABGESCHLOSSEN":
            return "IN_AKTE_UEBERFUEHRT"
        return normalized or "ERFASST"

    def _resolve_input_channel_prefix(self, payload: dict[str, object]) -> str:
        prefix = payload.get("inputChannelPrefix")
        if isinstance(prefix, str) and prefix.strip():
            return self._normalize_prefix(prefix)
        input_channel = payload.get("inputChannel")
        return self._derive_prefix_from_input_channel(
            input_channel if isinstance(input_channel, str) else ""
        )

    def _prefix_to_numeric(self, prefix: str) -> str:
        normalized_prefix = self._normalize_prefix(prefix)
        return "".join(f"{ord(character) - 64:02d}" for character in normalized_prefix)

    def _compute_mod10_check_digit(self, payload: str) -> int:
        total = 0
        weight = 2
        for character in reversed(payload):
            product = int(character) * weight
            if product > 9:
                product -= 9
            total += product
            weight = 1 if weight == 2 else 2
        return (10 - (total % 10)) % 10

    def _build_number(self, prefix: str, uniqueness_id: str, version: int) -> str:
        normalized_prefix = self._normalize_prefix(prefix)
        version_token = f"{max(0, version):03d}"
        payload = f"{self._prefix_to_numeric(normalized_prefix)}{uniqueness_id}{version_token}"
        check_digit = self._compute_mod10_check_digit(payload)
        return f"{normalized_prefix}-{uniqueness_id}-{version_token}-{check_digit}"

    def _parse_number(self, number: str) -> tuple[str, str, int, int] | None:
        parts = number.split("-")
        if len(parts) != 4:
            return None
        prefix, uniqueness_id, version_token, check_token = parts
        if not (prefix and uniqueness_id.isdigit() and len(uniqueness_id) == 8):
            return None
        if not (version_token.isdigit() and len(version_token) == 3):
            return None
        if not (check_token.isdigit() and len(check_token) == 1):
            return None
        normalized_prefix = self._normalize_prefix(prefix)
        if normalized_prefix != prefix:
            return None
        expected = self._build_number(normalized_prefix, uniqueness_id, int(version_token))
        if expected.split("-")[-1] != check_token:
            return None
        return normalized_prefix, uniqueness_id, int(version_token), int(check_token)

    def _parse_number_parts(self, number: str) -> tuple[str, str, int, int] | None:
        parts = number.split("-")
        if len(parts) != 4:
            return None
        prefix, uniqueness_id, version_token, check_token = parts
        if not prefix:
            return None
        normalized_prefix = self._normalize_prefix(prefix)
        if normalized_prefix != prefix:
            return None
        if not (uniqueness_id.isdigit() and len(uniqueness_id) == 8):
            return None
        if not (version_token.isdigit() and len(version_token) == 3):
            return None
        if not (check_token.isdigit() and len(check_token) == 1):
            return None
        return normalized_prefix, uniqueness_id, int(version_token), int(check_token)

    def _generate_uniqueness_id(self) -> str:
        return f"{secrets.randbelow(100_000_000):08d}"

    def _used_process_ids(self) -> set[str]:
        return set(self._store.keys())

    def _used_folder_numbers(self) -> set[str]:
        return {process.folder_number for process in self._store.values() if process.folder_number}

    def _generate_folder_number(self, prefix: str) -> str:
        normalized_prefix = self._normalize_prefix(prefix)
        used_numbers = self._used_folder_numbers()
        while True:
            folder_number = self._build_number(
                normalized_prefix,
                self._generate_uniqueness_id(),
                version=0,
            )
            if folder_number not in used_numbers:
                return folder_number

    def _generate_process_id(
        self,
        prefix: str,
        version: int = 0,
        fixed_uniqueness_id: str | None = None,
    ) -> str:
        normalized_prefix = self._normalize_prefix(prefix)
        used_ids = self._used_process_ids()
        if fixed_uniqueness_id:
            candidate = self._build_number(normalized_prefix, fixed_uniqueness_id, version)
            if candidate not in used_ids:
                return candidate
        while True:
            process_id = self._build_number(
                normalized_prefix,
                self._generate_uniqueness_id(),
                version,
            )
            if process_id not in used_ids:
                return process_id

    def _normalize_partner_sections(
        self,
        canonical_state: dict[str, object],
    ) -> dict[str, object]:
        partners = canonical_state.get("partners")
        if not isinstance(partners, list):
            return canonical_state

        normalized_partners: list[object] = []
        changed = False

        for partner in partners:
            if not isinstance(partner, dict):
                normalized_partners.append(partner)
                continue

            next_partner = dict(partner)

            occupation = next_partner.get("occupation")
            if not isinstance(occupation, dict):
                occupation = {}
            legacy_application_info = next_partner.get("applicationInformation")
            if isinstance(legacy_application_info, dict):
                occupation = {
                    "profession": occupation.get("profession", legacy_application_info.get("profession", "")),
                    "employmentGroup": occupation.get(
                        "employmentGroup",
                        legacy_application_info.get("employmentGroup", ""),
                    ),
                }
                next_partner.pop("applicationInformation", None)
                changed = True
            else:
                occupation = {
                    "profession": occupation.get("profession", ""),
                    "employmentGroup": occupation.get("employmentGroup", ""),
                }
            next_partner["occupation"] = occupation

            health = next_partner.get("health")
            if not isinstance(health, dict):
                health = {}
            legacy_health = next_partner.get("generalHealthInformation")
            if isinstance(legacy_health, dict):
                health = {
                    "height": health.get("height", legacy_health.get("height")),
                    "weight": health.get("weight", legacy_health.get("weight")),
                    "questionnaireResponses": health.get("questionnaireResponses", []),
                }
                next_partner.pop("generalHealthInformation", None)
                changed = True
            else:
                health = {
                    "height": health.get("height"),
                    "weight": health.get("weight"),
                    "questionnaireResponses": health.get("questionnaireResponses", []),
                }
            next_partner["health"] = health

            normalized_partners.append(next_partner)

        if not changed and normalized_partners == partners:
            return canonical_state
        return {**canonical_state, "partners": normalized_partners}

    def _normalize_insured_persons(
        self,
        canonical_state: dict[str, object],
    ) -> dict[str, object]:
        insured_persons = canonical_state.get("insuredPersons")
        if not isinstance(insured_persons, list):
            canonical_state["insuredPersons"] = [
                {
                    "insuredPersonId": "insured-person-1",
                    "person": {
                        "id": "insured-person-1",
                        "isLegalEntity": False,
                        "companyName": "",
                        "gender": "",
                        "salutation": "",
                        "academicTitle": "",
                        "familyStatus": "",
                        "firstname": "",
                        "lastname": "",
                        "birthDate": "",
                        "phone": "",
                        "email": "",
                        "nationality": "",
                        "address": {
                            "street": "",
                            "houseNumber": "",
                            "postalCode": "",
                            "city": "",
                            "country": "DE",
                        },
                        "occupation": {"profession": "", "employmentGroup": ""},
                    },
                    "health": {
                        "height": None,
                        "weight": None,
                        "questionnaire": {"availableQuestionIds": [], "responses": []},
                    },
                    "tariffSelection": {
                        "desiredCategories": [],
                        "availableTariffs": [],
                        "selectedTariffs": [],
                        "selectedLevels": {},
                        "riskSurcharges": {},
                        "totalMonthlyPrice": 0,
                    },
                    "documents": {"available": []},
                }
            ]
        runtime_context = canonical_state.get("runtimeContext")
        if not isinstance(runtime_context, dict):
            runtime_context = {}
        active_index = runtime_context.get("activeInsuredPersonIndex")
        if not isinstance(active_index, int) or active_index < 0:
            runtime_context["activeInsuredPersonIndex"] = 0
        canonical_state["runtimeContext"] = runtime_context
        return canonical_state

    def _insured_persons(self, canonical_state: dict[str, object]) -> list[dict[str, object]]:
        insured_persons = canonical_state.get("insuredPersons")
        if not isinstance(insured_persons, list):
            return []
        return [entry for entry in insured_persons if isinstance(entry, dict)]

    def _active_insured_person(self, canonical_state: dict[str, object]) -> dict[str, object] | None:
        insured_persons = self._insured_persons(canonical_state)
        if not insured_persons:
            return None
        runtime_context = canonical_state.get("runtimeContext")
        active_index = (
            runtime_context.get("activeInsuredPersonIndex")
            if isinstance(runtime_context, dict)
            else 0
        )
        if not isinstance(active_index, int) or active_index < 0 or active_index >= len(insured_persons):
            active_index = 0
        return insured_persons[active_index]

    def _all_selected_tariff_ids(self, canonical_state: dict[str, object]) -> list[str]:
        selected: list[str] = []
        for insured_person in self._insured_persons(canonical_state):
            tariff_selection = insured_person.get("tariffSelection")
            if not isinstance(tariff_selection, dict):
                continue
            for tariff_id in tariff_selection.get("selectedTariffs", []):
                if isinstance(tariff_id, str) and tariff_id not in selected:
                    selected.append(tariff_id)
        return selected

    def _all_available_document_ids(self, canonical_state: dict[str, object]) -> list[str]:
        document_ids: list[str] = []
        for insured_person in self._insured_persons(canonical_state):
            documents = insured_person.get("documents")
            if not isinstance(documents, dict):
                continue
            for document_id in documents.get("available", []):
                if isinstance(document_id, str) and document_id not in document_ids:
                    document_ids.append(document_id)
        return document_ids

    def _normalize_loaded_process(self, process: SalesProcess) -> SalesProcess:
        normalized_status = self._normalize_status(process.status or "ERFASST")
        if process.is_archived and normalized_status != "ARCHIVIERT":
            normalized_status = "ARCHIVIERT"
        canonical_state = self._normalize_partner_sections(dict(process.canonical_state))
        canonical_state = self._normalize_insured_persons(canonical_state)
        canonical_state["status"] = self._normalize_status(str(canonical_state.get("status", normalized_status)))
        if process.is_archived:
            canonical_state["status"] = "ARCHIVIERT"
        canonical_state.setdefault("intermediaryNumber", process.intermediary_number)
        canonical_state.setdefault("inputChannel", "")
        canonical_state.setdefault("inputChannelPrefix", self._resolve_input_channel_prefix(canonical_state))
        canonical_state.setdefault("signatureRequired", False)
        canonical_state.setdefault("targetAudience", "VERMITTLER")
        canonical_state.setdefault("runtimeContext", {"activeInsuredPersonIndex": 0})

        created_at = process.created_at or self._timestamp()
        updated_at = process.updated_at or created_at
        folder_id = process.folder_id or process.id
        input_channel_prefix = self._resolve_input_channel_prefix(canonical_state)
        folder_number = process.folder_number or self._generate_folder_number(input_channel_prefix)
        intermediary_number = (
            process.intermediary_number
            or str(canonical_state.get("intermediaryNumber", ""))
        )
        case_file = process.case_file.model_copy(
            update={
                "signature_required": bool(canonical_state.get("signatureRequired", False)),
                "signature_status": (
                    process.case_file.signature_status
                    if process.case_file.status != "OFFEN"
                    else (
                        "OFFEN"
                        if bool(canonical_state.get("signatureRequired", False))
                        else "NICHT_ERFORDERLICH"
                    )
                ),
            }
        )

        return process.model_copy(
            update={
                "status": normalized_status,
                "created_at": created_at,
                "updated_at": updated_at,
                "folder_id": folder_id,
                "folder_number": folder_number,
                "variant_number": process.variant_number or 1,
                "intermediary_number": intermediary_number,
                "is_archived": bool(process.is_archived),
                "archived_at": process.archived_at,
                "archived_by_type": process.archived_by_type,
                "archived_by_id": process.archived_by_id,
                "archive_reason": process.archive_reason,
                "last_active_status": process.last_active_status
                or (normalized_status if process.is_archived else None),
                "canonical_state": canonical_state,
                "case_file": case_file,
            }
        )

    def _append_history(
        self,
        process: SalesProcess,
        event: str,
        from_status: str,
        to_status: str,
        metadata: dict[str, object] | None = None,
    ) -> SalesProcess:
        if from_status == to_status and event not in {
            "CREATE_SALES_PROCESS",
            "GENERATE_PROPOSAL",
            "GENERATE_APPLICATION",
        }:
            return process
        return process.model_copy(
            update={
                "history": [
                    *process.history,
                    SalesProcessHistoryEntry(
                        event=event,
                        from_status=from_status,
                        to_status=to_status,
                        changed_at=self._timestamp(),
                        metadata=metadata or {},
                    ),
                ]
            }
        )

    def _with_status(self, process: SalesProcess, status: str) -> SalesProcess:
        normalized_status = self._normalize_status(status)
        canonical_state = dict(process.canonical_state)
        canonical_state["status"] = normalized_status
        return process.model_copy(
            update={
                "status": normalized_status,
                "updated_at": self._timestamp(),
                "canonical_state": canonical_state,
            }
        )

    def _close_sibling_processes(self, process: SalesProcess, reason: str) -> None:
        for sibling_id, sibling in list(self._store.items()):
            if sibling_id == process.id or sibling.folder_id != process.folder_id:
                continue
            if sibling.status == "GESCHLOSSEN":
                continue
            updated = self._with_status(sibling, "GESCHLOSSEN")
            updated = self._append_history(
                updated,
                event=reason,
                from_status=sibling.status,
                to_status="GESCHLOSSEN",
                metadata={"leading_process_id": process.id},
            )
            self._store[sibling_id] = updated

    def _base_variant_state(self, process: SalesProcess, new_process_id: str) -> dict[str, object]:
        canonical_state = deepcopy(process.canonical_state)
        canonical_state["id"] = new_process_id
        canonical_state["status"] = status_engine_service.get_engine(process.status_engine_version).initialStatus
        canonical_state["documents"] = {
            **canonical_state.get("documents", {}),
            "proposalType": canonical_state.get("documents", {}).get("proposalType", "VVG"),
        }
        return canonical_state

    def _build_case_file(
        self,
        canonical_state: dict[str, object] | None = None,
    ) -> SalesProcessCaseFile:
        signature_required = bool((canonical_state or {}).get("signatureRequired", False))
        return SalesProcessCaseFile(
            status="OFFEN",
            signature_required=signature_required,
            signature_status="OFFEN" if signature_required else "NICHT_ERFORDERLICH",
        )

    def _is_locked(self, process: SalesProcess) -> bool:
        return process.is_archived or process.status in {
            "IN_AKTE_UEBERFUEHRT",
            "UNTERSCHRIFT_AUSSTEHEND",
            "UNTERSCHRIEBEN",
            "ANTRAG_EINGEREICHT",
            "GESCHLOSSEN",
            "ARCHIVIERT",
        }

    def _update_case_file_documents(
        self,
        process: SalesProcess,
        document: GeneratedDocumentRecord,
    ) -> SalesProcessCaseFile:
        has_application = document.document_kind == "APPLICATION" or any(
            entry.document_kind == "APPLICATION" for entry in process.generated_documents
        )
        return process.case_file.model_copy(
            update={
                "generated_document_ids": list(
                    dict.fromkeys([*process.case_file.generated_document_ids, document.id])
                ),
                "supporting_document_ids": list(
                    dict.fromkeys(
                        [
                            *process.case_file.supporting_document_ids,
                            *self._all_available_document_ids(process.canonical_state),
                            *document.required_documents,
                        ]
                    )
                ),
                "submission_ready": (
                    has_application
                    and not process.case_file.signature_required
                    and document.submission.allowed
                )
                or process.case_file.submission_ready,
            }
        )

    def _build_tariff_table(self, canonical_state: dict) -> list[dict[str, object]]:
        selected_tariffs = self._all_selected_tariff_ids(canonical_state)
        active_insured_person = self._active_insured_person(canonical_state) or {}
        tariff_selection = (
            active_insured_person.get("tariffSelection")
            if isinstance(active_insured_person.get("tariffSelection"), dict)
            else {}
        )
        risk_surcharges = tariff_selection.get("riskSurcharges", {}) if isinstance(tariff_selection, dict) else {}
        tariff_catalog = tariff_service.get_catalog("v1")
        rows: list[dict[str, object]] = []
        for tariff in tariff_catalog.tariffs:
            if tariff.id not in selected_tariffs:
                continue
            risk_surcharge = float(risk_surcharges.get(tariff.id, 0) or 0)
            calculation = tariff_service.calculate_tariff_amount(
                TariffCalculationRequest(tariffId=tariff.id, canonicalState=canonical_state)
            )
            payable_without_risk = (
                float(calculation.details.get("payableAmount", 0) or 0)
                if calculation.source == "EXTERNAL"
                else calculate_tariff_payable_price(tariff, canonical_state, tariff_catalog.tariffs)
            )
            tariff_price = calculation.amount
            rows.append(
                {
                    "id": tariff.id,
                    "category": tariff.category,
                    "name": tariff.externalName,
                    "tariffPrice": tariff_price,
                    "legalSurcharge": max(0.0, payable_without_risk - tariff_price),
                    "riskSurcharge": risk_surcharge,
                    "payablePrice": payable_without_risk + risk_surcharge,
                }
            )
        return rows

    def _build_tariff_cost_table(self, canonical_state: dict) -> list[dict[str, object]]:
        selected_tariffs = self._all_selected_tariff_ids(canonical_state)
        tariff_catalog = tariff_service.get_catalog("v1")
        rows: list[dict[str, object]] = []
        for tariff in tariff_catalog.tariffs:
            if tariff.id not in selected_tariffs:
                continue
            one_time_amount, _ = tariff_service.calculate_cost_component_amount(
                tariff,
                tariff.costs.acquisitionAndDistributionOneTime,
                0,
                canonical_state,
                tariff_catalog.tariffs,
                "ACQUISITION_AND_DISTRIBUTION_ONE_TIME",
            )
            monthly_amount, _ = tariff_service.calculate_cost_component_amount(
                tariff,
                tariff.costs.acquisitionAndDistributionMonthly,
                0,
                canonical_state,
                tariff_catalog.tariffs,
                "ACQUISITION_AND_DISTRIBUTION_MONTHLY",
            )
            admin_amount, _ = tariff_service.calculate_cost_component_amount(
                tariff,
                tariff.costs.administrationConsultingAndSupportMonthly,
                0,
                canonical_state,
                tariff_catalog.tariffs,
                "ADMINISTRATION_CONSULTING_SUPPORT_MONTHLY",
            )
            rows.append(
                {
                    "id": tariff.id,
                    "category": tariff.category,
                    "name": tariff.externalName,
                    "oneTimeAcquisitionAndDistribution": one_time_amount,
                    "monthlyAcquisitionAndDistribution": monthly_amount,
                    "administrationConsultingAndSupport": admin_amount,
                }
            )
        return rows

    def _build_contribution_development_table(self, canonical_state: dict) -> list[dict[str, object]]:
        selected_tariffs = self._all_selected_tariff_ids(canonical_state)
        tariff_catalog = tariff_service.get_catalog("v1")
        rows: list[dict[str, object]] = []
        for tariff in tariff_catalog.tariffs:
            if tariff.id not in selected_tariffs:
                continue
            reference_age = tariff.contributionDevelopment.referenceEntryAge or 35
            configured_start_year = tariff.contributionDevelopment.startYear or 2016
            configured_end_year = tariff.contributionDevelopment.endYear or configured_start_year
            year_count = max(1, configured_end_year - configured_start_year + 1)
            development_rows = (
                tariff.contributionDevelopment.rows
                if tariff.contributionDevelopment.rows
                else [
                    {
                        "policyYear": index + 1,
                        "attainedAge": reference_age + index,
                        "payablePrice": round(
                            calculate_tariff_payable_price(
                                tariff, canonical_state, tariff_catalog.tariffs
                            )
                            * (0.92 + index * 0.015),
                            2,
                        ),
                    }
                    for index in range(year_count)
                ]
            )
            for row in development_rows:
                row_payload = row.model_dump() if hasattr(row, "model_dump") else dict(row)
                policy_year = int(row_payload.get("policyYear", 1) or 1)
                rows.append(
                    {
                        "tariffId": tariff.id,
                        "tariffName": tariff.externalName,
                        "policyYear": policy_year,
                        "year": configured_start_year + max(0, policy_year - 1),
                        "attainedAge": row_payload.get("attainedAge", reference_age),
                        "payablePrice": row_payload.get("payablePrice", 0),
                    }
                )
        return rows

    def _build_generated_input_snapshot(
        self,
        process: SalesProcess,
        document_kind: str,
    ) -> tuple[dict[str, object], dict[str, object], str]:
        artifact = document_output_service.get_config("v1")
        profile = artifact.proposal if document_kind == "PROPOSAL" else artifact.application
        title = profile.generatedConfig.titleTemplate.replace("{{salesProcessId}}", process.id)
        input_snapshot: dict[str, object] = {}

        for section in profile.generatedConfig.sections:
            section_payload: list[dict[str, object]] = []
            for document_input in section.inputs:
                if document_input.type == "TARIFF_TABLE":
                    value = self._build_tariff_table(process.canonical_state)
                elif document_input.type == "TARIFF_COST_TABLE":
                    value = self._build_tariff_cost_table(process.canonical_state)
                elif document_input.type == "CONTRIBUTION_DEVELOPMENT_TABLE":
                    value = self._build_contribution_development_table(process.canonical_state)
                else:
                    value = (
                        resolve_binding(process.canonical_state, document_input.binding)
                        if document_input.binding
                        else None
                    )
                section_payload.append(
                    {
                        "id": document_input.id,
                        "label": document_input.label,
                        "type": document_input.type,
                        "binding": document_input.binding,
                        "signatureRole": getattr(document_input, "signatureRole", ""),
                        "editable": document_input.editable,
                        "required": document_input.required,
                        "value": value,
                    }
                )
            input_snapshot[section.id] = {
                "title": section.title,
                "description": section.description,
                "inputs": section_payload,
            }

        summary = {
            "headerText": profile.generatedConfig.headerText,
            "title": title,
            "logoUrl": profile.generatedConfig.logoUrl,
            "notices": profile.generatedConfig.notices,
            "includeTimestamp": profile.generatedConfig.includeTimestamp,
            "includeSalesProcessId": profile.generatedConfig.includeSalesProcessId,
        }
        return input_snapshot, summary, profile.mode

    def _latest_document(
        self, process: SalesProcess, document_kind: str
    ) -> GeneratedDocumentRecord | None:
        for document in reversed(process.generated_documents):
            if document.document_kind == document_kind:
                return document
        return None

    def _build_response(
        self,
        process: SalesProcess,
        document: GeneratedDocumentRecord,
    ) -> GeneratedDocumentResponse:
        return GeneratedDocumentResponse(
            document_id=document.id,
            sales_process_id=process.id,
            document_kind=document.document_kind,
            mode=document.mode,
            variant=document.variant,
            version_number=document.version_number,
            file_name=document.file_name,
            mime_type=document.mime_type,
            generated_at=document.generated_at,
            status=process.status,
            storage_reference=document.storage_reference,
            required_documents=document.required_documents,
            summary=document.summary,
        )

    def _find_document(
        self,
        document_id: str,
        document_kind: str | None = None,
    ) -> tuple[SalesProcess, GeneratedDocumentRecord]:
        for process in self._store.values():
            for document in process.generated_documents:
                if document.id != document_id:
                    continue
                if document_kind and document.document_kind != document_kind:
                    continue
                return process, document
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden.")

    def _find_uploaded_document(
        self,
        process: SalesProcess,
        upload_id: str,
    ) -> UserUploadedDocumentRecord:
        document = next((item for item in process.uploaded_documents if item.id == upload_id), None)
        if document is None:
            raise HTTPException(status_code=404, detail="Hochgeladenes Dokument nicht gefunden.")
        return document

    def _sanitize_upload_file_name(self, file_name: str) -> str:
        candidate = Path(file_name).name.strip() or "upload"
        sanitized = "".join(
            character
            for character in candidate
            if character.isalnum() or character in {"-", "_", ".", " "}
        ).strip()
        return sanitized or "upload"

    def _escape_pdf_text(self, value: object) -> str:
        text = str(value)
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _pdf_text_command(
        self,
        text: object,
        x: float,
        y: float,
        font: str,
        size: float,
        color: tuple[float, float, float],
    ) -> str:
        escaped = self._escape_pdf_text(text)
        return (
            "BT "
            f"/{font} {size:.2f} Tf "
            f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({escaped}) Tj ET"
        )

    def _pdf_rect_command(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = None,
        line_width: float = 1,
    ) -> str:
        commands: list[str] = ["q"]
        if line_width != 1:
            commands.append(f"{line_width:.2f} w")
        if fill is not None:
            commands.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke is not None:
            commands.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG")
        commands.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re")
        if fill is not None and stroke is not None:
            commands.append("B")
        elif fill is not None:
            commands.append("f")
        else:
            commands.append("S")
        commands.append("Q")
        return "\n".join(commands)

    def _wrap_pdf_text(self, text: object, font_size: float, max_width: float) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        approximate_char_width = max(font_size * 0.5, 4.2)
        max_chars = max(8, int(max_width / approximate_char_width))

        def split_long_word(word: str) -> list[str]:
            if len(word) <= max_chars:
                return [word]
            return [word[index : index + max_chars] for index in range(0, len(word), max_chars)]

        lines: list[str] = []
        current = ""
        for word in raw.split():
            word_parts = split_long_word(word)
            if len(word_parts) > 1:
                if current:
                    lines.append(current)
                    current = ""
                lines.extend(word_parts[:-1])
                word = word_parts[-1]
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def _wrapped_text_height(
        self,
        text: object,
        font_size: float,
        max_width: float,
        line_height: float | None = None,
    ) -> float:
        lines = self._wrap_pdf_text(text, font_size, max_width)
        if not lines:
            return 0.0
        return len(lines) * (line_height or font_size + 3)

    def _render_wrapped_text(
        self,
        operations: list[str],
        text: object,
        x: float,
        y: float,
        width: float,
        font: str,
        size: float,
        color: tuple[float, float, float],
        line_height: float | None = None,
    ) -> float:
        lines = self._wrap_pdf_text(text, size, width)
        next_y = y
        step = line_height or size + 3
        for line in lines:
            operations.append(self._pdf_text_command(line, x, next_y, font, size, color))
            next_y -= step
        return next_y

    def _extract_tariff_rows(self, input_snapshot: dict[str, object]) -> list[dict[str, object]]:
        for section in input_snapshot.values():
            if not isinstance(section, dict):
                continue
            inputs = section.get("inputs", [])
            if not isinstance(inputs, list):
                continue
            for entry in inputs:
                if not isinstance(entry, dict):
                    continue
                value = entry.get("value")
                if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                    first_row = value[0]
                    if isinstance(first_row, dict) and "payablePrice" in first_row:
                        return [item for item in value if isinstance(item, dict)]
        return []

    def _table_descriptor(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[list[str], list[float], list[list[str]]] | None:
        if not rows:
            return None
        first_row = rows[0]

        if "oneTimeAcquisitionAndDistribution" in first_row:
            return (
                [
                    "Kategorie",
                    "Tarif",
                    "Abschluss/Vertrieb einmalig",
                    "Abschluss/Vertrieb monatlich",
                    "Verwaltung/Beratung/Betreuung",
                ],
                [70.0, 110.0, 110.0, 110.0, 123.0],
                [
                    [
                        str(row.get("category", "-")),
                        str(row.get("name", "-")),
                        f"{float(row.get('oneTimeAcquisitionAndDistribution', 0) or 0):.2f} EUR",
                        f"{float(row.get('monthlyAcquisitionAndDistribution', 0) or 0):.2f} EUR",
                        f"{float(row.get('administrationConsultingAndSupport', 0) or 0):.2f} EUR",
                    ]
                    for row in rows
                ],
            )

        if "tariffName" in first_row and "policyYear" in first_row:
            return (
                ["Tarif", "Vertragsjahr", "Jahr", "Erreichtes Alter", "Beitrag"],
                [160.0, 78.0, 78.0, 98.0, 109.0],
                [
                    [
                        str(row.get("tariffName", "-")),
                        str(row.get("policyYear", "-")),
                        str(row.get("year", "-")),
                        str(row.get("attainedAge", "-")),
                        f"{float(row.get('payablePrice', 0) or 0):.2f} EUR",
                    ]
                    for row in rows
                ],
            )

        if "payablePrice" in first_row:
            return (
                ["Kategorie", "Tarif", "Beitrag", "Risiko", "Zahlbeitrag"],
                [84.0, 175.0, 84.0, 84.0, 96.0],
                [
                    [
                        str(row.get("category", "-")),
                        str(row.get("name", "-")),
                        f"{float(row.get('tariffPrice', 0) or 0):.2f} EUR",
                        f"{float(row.get('riskSurcharge', 0) or 0):.2f} EUR",
                        f"{float(row.get('payablePrice', 0) or 0):.2f} EUR",
                    ]
                    for row in rows
                ],
            )

        return None

    def _signature_role_label(self, role: object) -> str:
        labels = {
            "INSURED_PERSON": "Versicherte Person",
            "POLICY_HOLDER": "Versicherungsnehmer",
            "PAYMENT_CONTRIBUTOR": "Beitragszahler",
            "INTERMEDIARY": "Vermittler",
        }
        return labels.get(str(role or ""), "")

    def _format_pdf_value(self, value: object) -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, bool):
            return "Ja" if value else "Nein"
        if isinstance(value, float):
            return f"{value:.2f}"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _build_pdf_bytes(
        self,
        process: SalesProcess,
        document_kind: str,
        summary: dict[str, object],
        input_snapshot: dict[str, object],
    ) -> bytes:
        page_width = 595.0
        page_height = 842.0
        margin = 36.0
        content_width = page_width - 2 * margin
        pages: list[list[str]] = [[]]
        current_page = 0
        y = 0.0
        title = str(summary.get("title", document_kind))
        header_text = str(summary.get("headerText", ""))
        intermediary_number = str(resolve_binding(process.canonical_state, "intermediaryNumber") or "-")
        sub_intermediary_number = str(
            resolve_binding(process.canonical_state, "subIntermediaryNumber") or "-"
        )
        external_reference = str(
            resolve_binding(process.canonical_state, "externalApplicationNumber") or "-"
        )
        header_detail_bindings = {
            "intermediaryNumber",
            "subIntermediaryNumber",
            "externalApplicationNumber",
        }

        def page_ops() -> list[str]:
            return pages[current_page]

        def add_page() -> float:
            nonlocal current_page
            pages.append([])
            current_page += 1
            ops = page_ops()
            top_y = page_height - margin - 14
            ops.append(
                self._pdf_text_command(
                    title,
                    margin,
                    top_y,
                    "F2",
                    11,
                    (0.08, 0.12, 0.2),
                )
            )
            ops.append(
                self._pdf_text_command(
                    document_kind,
                    page_width - margin - 80,
                    top_y,
                    "F1",
                    8,
                    (0.45, 0.52, 0.59),
                )
            )
            ops.append(
                self._pdf_rect_command(
                    margin,
                    top_y - 10,
                    content_width,
                    0.5,
                    stroke=(0.87, 0.91, 0.95),
                    line_width=0.5,
                )
            )
            return top_y - 28

        def ensure_space(required_height: float) -> None:
            nonlocal y
            minimum_bottom = margin + 34
            if y - required_height < minimum_bottom:
                y = add_page()

        hero_y = 712.0
        hero_height = 106.0
        page_ops().append(
            self._pdf_rect_command(
                margin,
                hero_y,
                content_width,
                hero_height,
                fill=(0.08, 0.16, 0.29),
                stroke=(0.08, 0.16, 0.29),
            )
        )
        page_ops().append(
            self._pdf_rect_command(
                margin,
                hero_y + hero_height - 8,
                content_width,
                8,
                fill=(0.16, 0.57, 0.88),
                stroke=(0.16, 0.57, 0.88),
            )
        )
        page_ops().append(
            self._pdf_text_command(
                "Digitale Antragsstrecke",
                margin + 18,
                hero_y + hero_height - 24,
                "F2",
                9,
                (0.77, 0.91, 1.0),
            )
        )
        title_y = hero_y + hero_height - 50
        if header_text:
            title_y = self._render_wrapped_text(
                page_ops(),
                header_text,
                margin + 18,
                title_y,
                content_width - 210,
                "F2",
                18,
                (1.0, 1.0, 1.0),
                line_height=22,
            )
        self._render_wrapped_text(
            page_ops(),
            title,
            margin + 18,
            title_y - 6,
            content_width - 210,
            "F1",
            10,
            (0.84, 0.9, 0.97),
            line_height=13,
        )

        detail_box_x = page_width - margin - 168
        detail_box_width = 150
        detail_box_height = hero_height - 26
        detail_box_y = hero_y + 13
        page_ops().append(
            self._pdf_rect_command(
                detail_box_x,
                detail_box_y,
                detail_box_width,
                detail_box_height,
                fill=(1.0, 1.0, 1.0),
                stroke=(0.78, 0.86, 0.96),
            )
        )
        detail_rows = [
            ("Vertriebsvorgang", process.id if summary.get("includeSalesProcessId") else "-"),
            (
                "Erstelldatum",
                self._timestamp()[:19].replace("T", " ") if summary.get("includeTimestamp") else "-",
            ),
            ("Vermittlernr.", intermediary_number),
            ("Untervermittlernr.", sub_intermediary_number),
            ("Externe Referenz", external_reference),
        ]
        detail_y = detail_box_y + detail_box_height - 16
        for label, value in detail_rows:
            page_ops().append(
                self._pdf_text_command(label, detail_box_x + 10, detail_y, "F1", 7.5, (0.41, 0.48, 0.56))
            )
            detail_y = self._render_wrapped_text(
                page_ops(),
                value,
                detail_box_x + 10,
                detail_y - 10,
                detail_box_width - 20,
                "F2",
                8.5,
                (0.12, 0.17, 0.24),
                line_height=10.5,
            ) - 6

        if summary.get("logoUrl"):
            page_ops().append(
                self._pdf_rect_command(
                    detail_box_x - 70,
                    hero_y + 18,
                    52,
                    52,
                    fill=(1.0, 1.0, 1.0),
                    stroke=(0.79, 0.86, 0.93),
                )
            )
            page_ops().append(
                self._pdf_text_command(
                    "Logo",
                    detail_box_x - 55,
                    hero_y + 40,
                    "F2",
                    10,
                    (0.38, 0.47, 0.56),
                )
            )

        tariff_rows = self._extract_tariff_rows(input_snapshot)
        total_payable = sum(
            float(row.get("payablePrice", 0) or 0) for row in tariff_rows if isinstance(row, dict)
        )

        card_top = 676.0
        card_height = 62.0
        card_gap = 12.0
        card_width = (content_width - 2 * card_gap) / 3
        metadata = [
            ("Gesamtbeitrag", f"{total_payable:.2f} EUR"),
            ("Eingangskanal", str(resolve_binding(process.canonical_state, "inputChannel") or "-")),
            ("Status", process.status),
        ]
        for index, (label, value) in enumerate(metadata):
            x = margin + index * (card_width + card_gap)
            page_ops().append(
                self._pdf_rect_command(
                    x,
                    card_top - card_height,
                    card_width,
                    card_height,
                    fill=(0.97, 0.985, 1.0),
                    stroke=(0.84, 0.9, 0.97),
                )
            )
            page_ops().append(
                self._pdf_rect_command(
                    x,
                    card_top - 3,
                    card_width,
                    3,
                    fill=(0.16, 0.57, 0.88),
                    stroke=(0.16, 0.57, 0.88),
                )
            )
            page_ops().append(
                self._pdf_text_command(label, x + 14, card_top - 22, "F1", 8, (0.39, 0.47, 0.55))
            )
            self._render_wrapped_text(
                page_ops(),
                value,
                x + 14,
                card_top - 40,
                card_width - 28,
                "F2",
                12,
                (0.08, 0.12, 0.2),
                line_height=14,
            )

        y = 584.0
        notices = summary.get("notices", [])
        if isinstance(notices, list) and notices:
            notice_lines = sum(
                max(1, len(self._wrap_pdf_text(f"- {notice}", 9, content_width - 28)))
                for notice in notices
            )
            notice_height = 28 + notice_lines * 12 + 10
            page_ops().append(
                self._pdf_rect_command(
                    margin,
                    y - notice_height,
                    content_width,
                    notice_height,
                    fill=(0.96, 0.99, 0.97),
                    stroke=(0.79, 0.9, 0.83),
                )
            )
            page_ops().append(
                self._pdf_rect_command(
                    margin,
                    y - notice_height,
                    4,
                    notice_height,
                    fill=(0.22, 0.63, 0.36),
                    stroke=(0.22, 0.63, 0.36),
                )
            )
            page_ops().append(
                self._pdf_text_command("Hinweise", margin + 16, y - 18, "F2", 10, (0.15, 0.44, 0.28))
            )
            notice_y = y - 34
            for notice in notices:
                notice_y = self._render_wrapped_text(
                    page_ops(),
                    f"- {notice}",
                    margin + 16,
                    notice_y,
                    content_width - 30,
                    "F1",
                    9,
                    (0.22, 0.29, 0.35),
                    line_height=12,
                )
            y -= notice_height + 26

        def render_table(
            table_headers: list[str],
            col_widths: list[float],
            row_values_list: list[list[str]],
        ) -> None:
            nonlocal y
            table_x = margin + 16
            table_width = sum(col_widths)
            if table_width > content_width - 32:
                scale = (content_width - 32) / table_width
                col_widths = [width * scale for width in col_widths]

            header_line_height = 10
            body_line_height = 10
            header_padding = 8
            body_padding = 8

            def draw_header() -> None:
                nonlocal y
                header_lines = [
                    self._wrap_pdf_text(header, 7.5, max(24.0, width - 10))
                    for header, width in zip(table_headers, col_widths)
                ]
                header_height = max(
                    20.0,
                    max(len(lines) for lines in header_lines) * header_line_height + header_padding,
                )
                ensure_space(header_height + 10)
                offset_x = table_x
                for index, header in enumerate(table_headers):
                    width = col_widths[index]
                    page_ops().append(
                        self._pdf_rect_command(
                            offset_x,
                            y - header_height,
                            width,
                            header_height,
                            fill=(0.12, 0.22, 0.38),
                            stroke=(0.12, 0.22, 0.38),
                        )
                    )
                    text_y = y - 11
                    for line in header_lines[index]:
                        page_ops().append(
                            self._pdf_text_command(
                                line,
                                offset_x + 5,
                                text_y,
                                "F2",
                                7.5,
                                (1.0, 1.0, 1.0),
                            )
                        )
                        text_y -= header_line_height
                    offset_x += width
                y -= header_height

            draw_header()
            for row_index, row_values in enumerate(row_values_list):
                cell_lines = [
                    self._wrap_pdf_text(cell, 8, max(24.0, width - 10))
                    for cell, width in zip(row_values, col_widths)
                ]
                row_height = max(
                    18.0,
                    max(len(lines) for lines in cell_lines) * body_line_height + body_padding,
                )
                if y - row_height < margin + 40:
                    y = add_page()
                    draw_header()

                offset_x = table_x
                row_fill = (1.0, 1.0, 1.0) if row_index % 2 == 0 else (0.978, 0.986, 0.995)
                for index, cell in enumerate(row_values):
                    width = col_widths[index]
                    page_ops().append(
                        self._pdf_rect_command(
                            offset_x,
                            y - row_height,
                            width,
                            row_height,
                            fill=row_fill,
                            stroke=(0.88, 0.92, 0.96),
                        )
                    )
                    text_y = y - 10
                    for line in cell_lines[index]:
                        page_ops().append(
                            self._pdf_text_command(
                                line,
                                offset_x + 5,
                                text_y,
                                "F1",
                                8,
                                (0.16, 0.22, 0.3),
                            )
                        )
                        text_y -= body_line_height
                    offset_x += width
                y -= row_height
            y -= 12

        for section in input_snapshot.values():
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title", "Sektion"))
            section_description = str(section.get("description", ""))
            inputs = section.get("inputs", [])
            if not isinstance(inputs, list):
                continue

            section_intro_height = 34 + self._wrapped_text_height(
                section_description,
                9,
                content_width - 32,
                12,
            )
            ensure_space(section_intro_height + 20)

            page_ops().append(
                self._pdf_rect_command(
                    margin,
                    y - section_intro_height + 2,
                    content_width,
                    section_intro_height,
                    fill=(0.975, 0.985, 1.0),
                    stroke=(0.88, 0.92, 0.97),
                )
            )
            page_ops().append(
                self._pdf_rect_command(
                    margin,
                    y - section_intro_height + 2,
                    4,
                    section_intro_height,
                    fill=(0.16, 0.57, 0.88),
                    stroke=(0.16, 0.57, 0.88),
                )
            )
            page_ops().append(
                self._pdf_text_command(section_title, margin + 14, y - 14, "F2", 15, (0.08, 0.12, 0.2))
            )
            y -= 34
            if section_description:
                y = self._render_wrapped_text(
                    page_ops(),
                    section_description,
                    margin + 14,
                    y,
                    content_width - 22,
                    "F1",
                    9,
                    (0.39, 0.47, 0.55),
                    line_height=12,
                )
            y -= 22

            for entry in inputs:
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("label", entry.get("id", "Feld")))
                binding = str(entry.get("binding", "") or "")
                value = entry.get("value")

                if binding in header_detail_bindings:
                    continue

                ensure_space(18)
                page_ops().append(
                    self._pdf_text_command(label, margin, y, "F1", 8, (0.39, 0.47, 0.55))
                )
                y -= 16

                if entry.get("type") == "SIGNATURE":
                    signature_role_label = self._signature_role_label(entry.get("signatureRole"))
                    signature_caption = (
                        f"Unterschrift {signature_role_label}"
                        if signature_role_label
                        else "Unterschrift"
                    )
                    ensure_space(42)
                    page_ops().append(
                        self._pdf_rect_command(
                            margin,
                            y - 22,
                            220,
                            0.8,
                            stroke=(0.58, 0.65, 0.73),
                            line_width=0.8,
                        )
                    )
                    page_ops().append(
                        self._pdf_text_command(
                            signature_caption,
                            margin,
                            y - 34,
                            "F1",
                            8,
                            (0.39, 0.47, 0.55),
                        )
                    )
                    y -= 44
                    continue

                if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                    first_row = value[0]
                    if isinstance(first_row, dict) and (
                        "payablePrice" in first_row
                        or "oneTimeAcquisitionAndDistribution" in first_row
                        or "tariffName" in first_row
                    ):
                        rows = [item for item in value if isinstance(item, dict)]
                        descriptor = self._table_descriptor(rows)
                        if descriptor is not None:
                            table_headers, col_widths, row_values_list = descriptor
                            y -= 4
                            render_table(table_headers, col_widths, row_values_list)
                            continue

                value_text = self._format_pdf_value(value)
                value_height = self._wrapped_text_height(value_text, 10, content_width, 13)
                ensure_space(max(16, value_height + 6))
                y = self._render_wrapped_text(
                    page_ops(),
                    value_text,
                    margin,
                    y,
                    content_width,
                    "F2",
                    10,
                    (0.08, 0.12, 0.2),
                    line_height=13,
                )
                y -= 10

            y -= 14

        for index, operations in enumerate(pages, start=1):
            footer_y = 18.0
            operations.append(
                self._pdf_text_command(
                    "Erstellt in der digitalen Antragsstrecke",
                    margin,
                    footer_y,
                    "F1",
                    8,
                    (0.45, 0.52, 0.59),
                )
            )
            operations.append(
                self._pdf_text_command(
                    f"{document_kind} | Seite {index}/{len(pages)}",
                    page_width - margin - 110,
                    footer_y,
                    "F2",
                    8,
                    (0.06, 0.43, 0.74),
                )
            )

        content_streams = [
            "\n".join(operations).encode("cp1252", errors="replace") for operations in pages
        ]
        page_count = len(content_streams)
        kids = " ".join(f"{5 + index * 2} 0 R" for index in range(page_count))
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
        for index, content_stream in enumerate(content_streams):
            page_object_id = 5 + index * 2
            content_object_id = 6 + index * 2
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_object_id} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode(
                    "ascii"
                )
            )
            objects.append(
                b"<< /Length "
                + str(len(content_stream)).encode("ascii")
                + b" >>\nstream\n"
                + content_stream
                + b"\nendstream"
            )

        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode("ascii"))
            pdf.extend(obj)
            pdf.extend(b"\nendobj\n")

        xref_offset = len(pdf)
        pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF"
            ).encode("ascii")
        )
        return bytes(pdf)

    def _write_generated_pdf(
        self,
        process: SalesProcess,
        document: GeneratedDocumentRecord,
    ) -> None:
        target = settings.storage_root / document.storage_reference
        target.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = self._build_pdf_bytes(
            process,
            document.document_kind,
            document.summary,
            document.input_snapshot,
        )
        target.write_bytes(pdf_bytes)

    def _write_document_bytes(self, storage_reference: str, content: bytes) -> None:
        target = settings.storage_root / storage_reference
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def _execute_external_document(
        self,
        process: SalesProcess,
        document_kind: str,
        file_name: str,
        variant: str,
        adapter_id: str,
        endpoint: str,
        auth_type: str,
        template_id: str,
        payload_mapping: str,
        input_snapshot: dict[str, object],
        summary: dict[str, object],
    ) -> tuple[dict[str, object], bytes]:
        payload = {
            "adapterId": adapter_id,
            "templateId": template_id,
            "payloadMapping": payload_mapping,
            "documentKind": document_kind,
            "variant": variant,
            "salesProcessId": process.id,
            "fileName": file_name,
            "canonicalState": process.canonical_state,
            "summary": summary,
            "inputSnapshot": input_snapshot,
        }

        if adapter_id == "OMS_MOCK":
            mock_summary = {
                "externalOperation": {
                    "adapterId": adapter_id,
                    "status": "MOCK",
                    "templateId": template_id,
                }
            }
            mock_pdf = self._build_pdf_bytes(
                process,
                document_kind,
                {
                    **summary,
                    "headerText": f"{summary.get('headerText', '')} (extern ausgelöst)".strip(),
                    "notices": [
                        "Dieses Dokument wurde über den Mock-Adapter des externen Output-Managements erzeugt.",
                        *summary.get("notices", []),
                    ],
                },
                input_snapshot,
            )
            return mock_summary, mock_pdf

        response = post_json(endpoint, payload, auth_type)
        content_type = response.headers.get("Content-Type", "")
        response_payload: dict[str, object] = {}
        pdf_bytes = b""

        if "application/pdf" in content_type:
            pdf_bytes = response.body
        else:
            response_payload = response.json()
            pdf_base64 = (
                response_payload.get("pdfBase64")
                or response_payload.get("pdf_base64")
                or response_payload.get("contentBase64")
            )
            if isinstance(pdf_base64, str) and pdf_base64:
                pdf_bytes = base64.b64decode(pdf_base64)

        external_summary = {
            "externalOperation": {
                "adapterId": adapter_id,
                "status": "SUCCESS",
                "endpoint": endpoint,
                "templateId": template_id,
                "response": {
                    key: value
                    for key, value in response_payload.items()
                    if key not in {"pdfBase64", "pdf_base64", "contentBase64"}
                },
            }
        }

        if not pdf_bytes:
            pdf_bytes = self._build_pdf_bytes(
                process,
                document_kind,
                {
                    **summary,
                    "headerText": f"{summary.get('headerText', '')} (extern angefordert)".strip(),
                    "notices": [
                        "Das externe Output-Management hat kein PDF zurueckgeliefert. Daher wurde eine lokale Nachweisdarstellung erzeugt.",
                        *summary.get("notices", []),
                    ],
                },
                input_snapshot,
            )
            external_summary["externalOperation"]["status"] = "SUCCESS_WITH_FALLBACK"

        return external_summary, pdf_bytes

    def download_generated_document(self, process_id: str, document_id: str) -> Path:
        process = self._store[process_id]
        document = next((item for item in process.generated_documents if item.id == document_id), None)
        if document is None:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden.")
        target = settings.storage_root / document.storage_reference
        if not target.exists():
            self._write_generated_pdf(process, document)
        return target

    def get_document_response(
        self,
        document_id: str,
        document_kind: str | None = None,
    ) -> GeneratedDocumentResponse:
        process, document = self._find_document(document_id, document_kind)
        return self._build_response(process, document)

    def download_document_by_id(
        self,
        document_id: str,
        document_kind: str | None = None,
    ) -> Path:
        process, document = self._find_document(document_id, document_kind)
        target = settings.storage_root / document.storage_reference
        if not target.exists():
            if document.mode == "EXTERNAL":
                raise HTTPException(status_code=404, detail="Dokumentdatei nicht gefunden.")
            self._write_generated_pdf(process, document)
        return target

    def upload_case_file_document(
        self,
        process_id: str,
        request: UploadSalesProcessDocumentRequest,
    ) -> SalesProcess:
        process = self._store[process_id]
        if process.case_file.status == "OFFEN":
            raise HTTPException(
                status_code=409,
                detail="Dokumente koennen erst nach dem Abschluss in die Vertriebsvorgangsakte geladen werden.",
            )

        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Ungueltige Base64-Daten fuer Dokumentupload.") from exc

        upload_number = len(process.uploaded_documents) + 1
        upload_id = f"{process_id}-upload-{upload_number}"
        existing_upload_ids = {item.id for item in process.uploaded_documents}
        while upload_id in existing_upload_ids:
            upload_number += 1
            upload_id = f"{process_id}-upload-{upload_number}"
        sanitized_name = self._sanitize_upload_file_name(request.file_name)
        storage_reference = f"uploads/{process_id}/{upload_id}-{sanitized_name}"
        self._write_document_bytes(storage_reference, content)

        uploaded_document = UserUploadedDocumentRecord(
            id=upload_id,
            file_name=sanitized_name,
            mime_type=request.mime_type or "application/octet-stream",
            uploaded_at=self._timestamp(),
            storage_reference=storage_reference,
            document_type=request.document_type,
            include_for_submission=request.include_for_submission,
        )
        case_file = process.case_file.model_copy(
            update={
                "uploaded_document_ids": list(
                    dict.fromkeys([*process.case_file.uploaded_document_ids, upload_id])
                )
            }
        )
        updated = process.model_copy(
            update={
                "updated_at": self._timestamp(),
                "uploaded_documents": [*process.uploaded_documents, uploaded_document],
                "case_file": case_file,
            }
        )
        self._store[process_id] = updated
        self._persist()
        return updated

    def download_uploaded_document(self, process_id: str, upload_id: str) -> tuple[Path, str]:
        process = self._store[process_id]
        document = self._find_uploaded_document(process, upload_id)
        target = settings.storage_root / document.storage_reference
        if not target.exists():
            raise HTTPException(status_code=404, detail="Datei zum hochgeladenen Dokument nicht gefunden.")
        return target, document.mime_type

    def create(self, request: CreateSalesProcessRequest) -> SalesProcess:
        requested_id = request.id or ""
        if requested_id and requested_id in self._store:
            return self._store[requested_id]

        initial_status = status_engine_service.get_engine(request.status_engine_version).initialStatus
        timestamp = self._timestamp()
        intermediary_number = request.intermediary_number or str(
            request.canonical_state.get("intermediaryNumber", "")
        )
        input_channel = str(request.canonical_state.get("inputChannel", "") or "")
        input_channel_prefix = self._resolve_input_channel_prefix(request.canonical_state)
        process_id = requested_id or self._generate_process_id(input_channel_prefix)
        canonical_state = {
            **request.canonical_state,
            "id": process_id,
            "status": initial_status,
            "intermediaryNumber": intermediary_number,
            "inputChannel": input_channel,
            "inputChannelPrefix": input_channel_prefix,
            "signatureRequired": bool(request.canonical_state.get("signatureRequired", False)),
            "targetAudience": str(request.canonical_state.get("targetAudience", "VERMITTLER")),
        }
        process = SalesProcess.model_validate(
            {
                **request.model_dump(),
                "id": process_id,
                "status": initial_status,
                "created_at": timestamp,
                "updated_at": timestamp,
                "folder_id": process_id,
                "folder_number": self._generate_folder_number(input_channel_prefix),
                "variant_number": 1,
                "intermediary_number": intermediary_number,
                "is_archived": False,
                "archived_at": None,
                "archived_by_type": None,
                "archived_by_id": None,
                "archive_reason": None,
                "last_active_status": None,
                "canonical_state": canonical_state,
                "case_file": self._build_case_file(canonical_state),
            }
        )
        process = self._append_history(
            process,
            event="CREATE_SALES_PROCESS",
            from_status=initial_status,
            to_status=initial_status,
        )
        self._store[process.id] = process
        self._persist()
        return process

    def validate_number(self, number: str, kind: str) -> NumberValidationResponse:
        normalized_kind = "FOLDER" if kind == "FOLDER" else "SALES_PROCESS"
        parsed_parts = self._parse_number_parts(number)
        errors: list[str] = []

        if not parsed_parts:
            errors.append("Format ungueltig. Erwartet: [PREFIX]-[UNIQ8]-[VER3]-[CHK1].")
            return NumberValidationResponse(
                number=number,
                kind=normalized_kind,
                valid_format=False,
                valid_checksum=False,
                exists=False,
                errors=errors,
            )

        prefix, uniqueness_id, version, check_digit = parsed_parts
        expected_number = self._build_number(prefix, uniqueness_id, version)
        expected_check_digit = int(expected_number.split("-")[-1])
        valid_checksum = check_digit == expected_check_digit
        if not valid_checksum:
            errors.append("Pruefziffer ungueltig.")

        exists = (
            number in self._store
            if normalized_kind == "SALES_PROCESS"
            else number in {process.folder_number for process in self._store.values() if process.folder_number}
        )

        return NumberValidationResponse(
            number=number,
            kind=normalized_kind,
            valid_format=True,
            valid_checksum=valid_checksum,
            exists=exists,
            prefix=prefix,
            uniqueness_id=uniqueness_id,
            version=version,
            check_digit=check_digit,
            expected_check_digit=expected_check_digit,
            errors=errors,
        )

    def get(self, process_id: str) -> SalesProcess:
        self._apply_retention_policy()
        if process_id not in self._store:
            raise HTTPException(status_code=404, detail="Vertriebsvorgang nicht gefunden.")
        return self._store[process_id]

    def list(self) -> list[SalesProcess]:
        self._apply_retention_policy()
        return list(self._store.values())

    def list_page(
        self,
        *,
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
        self._apply_retention_policy()
        normalized_page = max(1, page)
        normalized_page_size = max(1, min(page_size, 200))
        normalized_sort_dir = "asc" if sort_dir.lower() == "asc" else "desc"

        normalized_bucket = status_bucket.strip().upper()
        candidates = set(self._store.keys())
        if not include_archived:
            candidates = {
                process_id
                for process_id in candidates
                if not self._store[process_id].is_archived
            }
        if normalized_bucket == "ARCHIVED":
            candidates = {
                process_id
                for process_id in set(self._store.keys())
                if self._store[process_id].is_archived
                or self._store[process_id].status == "ARCHIVIERT"
            }
        elif normalized_bucket == "SUBMITTED":
            candidates = {
                process_id
                for process_id in candidates
                if self._store[process_id].status == "ANTRAG_EINGEREICHT"
            }
        elif normalized_bucket == "IN_PROGRESS":
            candidates = {
                process_id
                for process_id in candidates
                if self._store[process_id].status != "ANTRAG_EINGEREICHT"
                and self._store[process_id].status != "ARCHIVIERT"
            }
        if status:
            candidates &= self._status_index.get(status, set())
        if input_channel.strip():
            candidates &= self._input_channel_index.get(input_channel.strip().lower(), set())

        items = [self._to_list_item(self._store[process_id]) for process_id in candidates]

        submission_range_token = submission_range.strip().upper()
        today = datetime.now(UTC).date()
        yesterday = today.fromordinal(today.toordinal() - 1)

        def contains(source: str, needle: str) -> bool:
            return needle.strip().lower() in source.lower()

        def within_submission_range(submitted_at: str | None) -> bool:
            if not submission_range_token:
                return True
            if not submitted_at:
                return False
            try:
                submitted_date = datetime.fromisoformat(submitted_at.replace("Z", "+00:00")).date()
            except ValueError:
                return False
            if submission_range_token == "TODAY":
                return submitted_date == today
            if submission_range_token == "YESTERDAY":
                return submitted_date == yesterday
            if submission_range_token == "LAST_7_DAYS":
                return submitted_date >= today.fromordinal(today.toordinal() - 6)
            if submission_range_token == "LAST_14_DAYS":
                return submitted_date >= today.fromordinal(today.toordinal() - 13)
            if submission_range_token == "LAST_30_DAYS":
                return submitted_date >= today.fromordinal(today.toordinal() - 29)
            return True

        policy_holder_token = policy_holder.strip().lower()
        intermediary_token = intermediary_number.strip()
        folder_token = folder_number.strip()
        process_token = process_number.strip()
        reference_token = external_reference_number.strip()

        filtered: list[SalesProcessListItem] = []
        for item in items:
            if not within_submission_range(item.submitted_at):
                continue
            if intermediary_token and not contains(item.intermediary_number, intermediary_token):
                continue
            if folder_token and not contains(item.folder_number, folder_token):
                continue
            if process_token and not contains(item.id, process_token):
                continue
            if reference_token and not contains(item.external_reference_number, reference_token):
                continue
            if policy_holder_token:
                full_name = f"{item.policy_holder_first_name} {item.policy_holder_last_name}".strip().lower()
                reverse_name = f"{item.policy_holder_last_name} {item.policy_holder_first_name}".strip().lower()
                if policy_holder_token not in full_name and policy_holder_token not in reverse_name:
                    continue
            filtered.append(item)

        def sort_key(entry: SalesProcessListItem) -> tuple[object, str]:
            if sort_by == "intermediaryNumber":
                return (entry.intermediary_number.lower(), entry.id)
            if sort_by == "processNumber":
                return (entry.id.lower(), entry.id)
            if sort_by == "policyHolderName":
                return (
                    f"{entry.policy_holder_last_name} {entry.policy_holder_first_name}".strip().lower(),
                    entry.id,
                )
            if sort_by == "status":
                return (entry.status.lower(), entry.id)
            return (entry.created_at, entry.id)

        reverse = normalized_sort_dir == "desc"
        filtered.sort(key=sort_key, reverse=reverse)

        total = len(filtered)
        total_pages = (total + normalized_page_size - 1) // normalized_page_size if total else 0
        start = (normalized_page - 1) * normalized_page_size
        end = start + normalized_page_size
        page_items = filtered[start:end]

        status_counts: dict[str, int] = {}
        input_channel_counts: dict[str, int] = {}
        folder_ids: set[str] = set()
        for item in filtered:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
            channel = item.input_channel or "Nicht gesetzt"
            input_channel_counts[channel] = input_channel_counts.get(channel, 0) + 1
            folder_ids.add(item.folder_id)

        aggregates = SalesProcessListAggregates(
            total_processes=total,
            total_folders=len(folder_ids),
            status_counts=status_counts,
            input_channel_counts=input_channel_counts,
        )

        return SalesProcessListResponse(
            items=page_items,
            total=total,
            page=normalized_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
            has_prev=normalized_page > 1,
            has_next=normalized_page < total_pages,
            aggregates=aggregates,
        )

    def update(
        self,
        process_id: str,
        request: UpdateSalesProcessRequest,
    ) -> SalesProcess:
        current = self._store[process_id]
        if current.is_archived:
            raise HTTPException(
                status_code=409,
                detail="Archivierte Vertriebsvorgaenge koennen nicht mehr bearbeitet werden.",
            )
        next_canonical_state = (
            current.canonical_state
            if self._is_locked(current) and request.canonical_state is not None
            else request.canonical_state or current.canonical_state
        )
        next_intermediary_number = str(
            next_canonical_state.get("intermediaryNumber", current.intermediary_number)
        )
        updated = current.model_copy(
            update={
                "updated_at": self._timestamp(),
                "intermediary_number": next_intermediary_number,
                "canonical_state": next_canonical_state,
                "case_file": current.case_file.model_copy(
                    update={
                        "signature_required": bool(next_canonical_state.get("signatureRequired", False)),
                        "signature_status": (
                            current.case_file.signature_status
                            if current.case_file.status != "OFFEN"
                            else (
                                "OFFEN"
                                if bool(next_canonical_state.get("signatureRequired", False))
                                else "NICHT_ERFORDERLICH"
                            )
                        ),
                    }
                ),
            }
        )

        if request.transition_event:
            next_status = status_engine_service.apply_event(
                current.status_engine_version,
                updated.status,
                request.transition_event,
            )
            updated = self._with_status(updated, next_status)
            updated = self._append_history(
                updated,
                event=request.transition_event,
                from_status=current.status,
                to_status=next_status,
            )
        elif request.status:
            normalized_request_status = self._normalize_status(request.status)
            updated = self._with_status(updated, normalized_request_status)
            updated = self._append_history(
                updated,
                event="MANUAL_STATUS_UPDATE",
                from_status=current.status,
                to_status=normalized_request_status,
            )

        if updated.status == "ANTRAG_EINGEREICHT":
            case_file_status = "EINGEREICHT"
            submitted_at = updated.case_file.submitted_at or self._timestamp()
            updated = updated.model_copy(
                update={
                    "case_file": updated.case_file.model_copy(
                        update={
                            "status": case_file_status,
                            "submitted_at": submitted_at,
                            "submission_ready": True,
                        }
                    )
                }
            )

        self._store[process_id] = updated
        if updated.status == "ANTRAG_EINGEREICHT":
            self._close_sibling_processes(updated, "CLOSE_AFTER_SUBMISSION")
        self._persist()
        return updated

    def finalize(
        self,
        process_id: str,
        request: FinalizeSalesProcessRequest,
    ) -> SalesProcess:
        process = self._store[process_id]
        if process.status in {"IN_AKTE_UEBERFUEHRT", "UNTERSCHRIFT_AUSSTEHEND", "UNTERSCHRIEBEN"}:
            return process
        if process.status in {"ANTRAG_EINGEREICHT", "GESCHLOSSEN"}:
            raise HTTPException(status_code=409, detail="Der Vertriebsvorgang kann nicht mehr abgeschlossen werden.")

        application_document = self._latest_document(process, "APPLICATION")
        if application_document is None:
            raise HTTPException(status_code=409, detail="Vor dem Abschluss muss ein Antrag erzeugt werden.")

        if process.case_file.signature_required:
            next_status = status_engine_service.apply_event(
                process.status_engine_version,
                process.status,
                "FINALIZE_SALES_PROCESS",
            )
            next_status = status_engine_service.apply_event(
                process.status_engine_version,
                next_status,
                "REQUEST_SIGNATURE",
            )
        else:
            next_status = status_engine_service.apply_event(
                process.status_engine_version,
                process.status,
                "FINALIZE_SALES_PROCESS",
            )

        snapshot = deepcopy(process.canonical_state)
        visible_document_ids = request.visible_document_ids or list(
            dict.fromkeys(self._all_available_document_ids(process.canonical_state))
        )
        supporting_document_ids = request.supporting_document_ids or list(
            dict.fromkeys([*visible_document_ids, *process.case_file.supporting_document_ids])
        )
        generated_document_ids = [document.id for document in process.generated_documents]
        signature_status = (
            "OFFEN" if process.case_file.signature_required else "NICHT_ERFORDERLICH"
        )
        submission_ready = (
            not process.case_file.signature_required and application_document.submission.allowed
        )

        updated = self._with_status(process, next_status)
        updated = updated.model_copy(
            update={
                "case_file": updated.case_file.model_copy(
                    update={
                        "status": "ABGESCHLOSSEN",
                        "finalized_at": self._timestamp(),
                        "snapshot_version": max(1, updated.case_file.snapshot_version),
                        "read_only_snapshot": snapshot,
                        "visible_document_ids": visible_document_ids,
                        "generated_document_ids": generated_document_ids,
                        "supporting_document_ids": supporting_document_ids,
                        "signature_required": bool(updated.case_file.signature_required),
                        "signature_status": signature_status,
                        "submission_ready": submission_ready,
                    }
                )
            }
        )
        updated = self._append_history(
            updated,
            event="FINALIZE_SALES_PROCESS",
            from_status=process.status,
            to_status=next_status,
            metadata={
                "visible_document_ids": visible_document_ids,
                "supporting_document_ids": supporting_document_ids,
            },
        )

        self._store[process_id] = updated
        self._persist()
        return updated

    def create_variant(
        self,
        process_id: str,
        request: CreateVariantRequest,
    ) -> SalesProcess:
        source = self._store[process_id]
        if source.is_archived:
            raise HTTPException(
                status_code=409,
                detail="Archivierte Vertriebsvorgaenge koennen nicht variiert werden.",
            )
        existing_variant_numbers = [
            process.variant_number
            for process in self._store.values()
            if process.folder_id == source.folder_id
        ]
        next_variant_number = (max(existing_variant_numbers) if existing_variant_numbers else 0) + 1
        next_version = max(0, next_variant_number - 1)
        input_channel_prefix = self._resolve_input_channel_prefix(source.canonical_state)
        parsed_source_id = self._parse_number(source.id)
        fixed_uniqueness_id = parsed_source_id[1] if parsed_source_id else None
        prefix = parsed_source_id[0] if parsed_source_id else input_channel_prefix
        new_process_id = self._generate_process_id(
            prefix,
            version=next_version,
            fixed_uniqueness_id=fixed_uniqueness_id,
        )
        timestamp = self._timestamp()
        canonical_state = self._base_variant_state(source, new_process_id)
        intermediary_number = request.intermediary_number or source.intermediary_number

        variant = SalesProcess(
            id=new_process_id,
            flow_id=source.flow_id,
            flow_version=source.flow_version,
            status_engine_version=source.status_engine_version,
            status=status_engine_service.get_engine(source.status_engine_version).initialStatus,
            created_at=timestamp,
            updated_at=timestamp,
            folder_id=source.folder_id,
            folder_number=source.folder_number,
            variant_number=next_variant_number,
            source_process_id=source.id,
            intermediary_number=intermediary_number,
            canonical_state={
                **canonical_state,
                "intermediaryNumber": intermediary_number,
            },
            history=[],
            generated_documents=[],
            case_file=self._build_case_file(canonical_state),
        )
        variant = self._append_history(
            variant,
            event="CREATE_VARIANT",
            from_status=variant.status,
            to_status=variant.status,
            metadata={"source_process_id": source.id, "variant_number": next_variant_number},
        )
        self._store[variant.id] = variant
        self._persist()
        return variant

    def delete(self, process_id: str) -> None:
        self._store.pop(process_id, None)
        self._persist()

    def delete_folder(self, folder_id: str) -> int:
        process_ids = [
            process_id
            for process_id, process in self._store.items()
            if process.folder_id == folder_id
        ]
        for process_id in process_ids:
            self._store.pop(process_id, None)
        self._persist()
        return len(process_ids)

    def archive(self, process_id: str, request: ArchiveSalesProcessRequest) -> SalesProcess:
        process = self._store[process_id]
        if process.is_archived:
            return process
        previous_status = process.status
        canonical_state = dict(process.canonical_state)
        canonical_state["status"] = "ARCHIVIERT"
        updated = process.model_copy(
            update={
                "updated_at": self._timestamp(),
                "status": "ARCHIVIERT",
                "canonical_state": canonical_state,
                "is_archived": True,
                "archived_at": self._timestamp(),
                "archived_by_type": request.archived_by_type,
                "archived_by_id": request.archived_by_id or "",
                "archive_reason": request.reason,
                "last_active_status": previous_status,
            }
        )
        updated = self._append_history(
            updated,
            event="ARCHIVE_SALES_PROCESS",
            from_status=previous_status,
            to_status="ARCHIVIERT",
            metadata={
                "archived_by_type": request.archived_by_type,
                "archived_by_id": request.archived_by_id or "",
                "reason": request.reason or "",
            },
        )
        self._store[process_id] = updated
        self._persist()
        return updated

    def archive_folder(self, folder_id: str, request: ArchiveSalesProcessRequest) -> int:
        affected = 0
        for process_id, process in list(self._store.items()):
            if process.folder_id != folder_id or process.is_archived:
                continue
            self.archive(process_id, request)
            affected += 1
        self._persist()
        return affected

    def restore(self, process_id: str, request: RestoreSalesProcessRequest) -> SalesProcess:
        process = self._store[process_id]
        if not process.is_archived:
            return process
        policy = self._load_retention_policy(process.flow_id, process.flow_version)
        allow_restore = bool(policy.get("allowRestoreArchived", True)) if isinstance(policy, dict) else True
        if not allow_restore:
            raise HTTPException(
                status_code=409,
                detail="Die Wiederherstellung archivierter Vorgaenge ist im Loeschkonzept deaktiviert.",
            )
        final_statuses = {"ANTRAG_EINGEREICHT", "POLICIERT"}
        last_status = self._normalize_status(process.last_active_status or "")
        current_status = self._normalize_status(process.status or "")
        if (
            process.case_file.submitted_at
            or process.case_file.policy_issued_at
            or last_status in final_statuses
            or current_status in final_statuses
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Eingereichte oder policiierte Antraege koennen nicht wiederhergestellt werden."
                ),
            )
        target_status = self._normalize_status(process.last_active_status or "IN_AKTE_UEBERFUEHRT")
        canonical_state = dict(process.canonical_state)
        canonical_state["status"] = target_status
        restored = process.model_copy(
            update={
                "updated_at": self._timestamp(),
                "status": target_status,
                "canonical_state": canonical_state,
                "is_archived": False,
                "archived_at": None,
                "archived_by_type": None,
                "archived_by_id": None,
                "archive_reason": None,
            }
        )
        restored = self._append_history(
            restored,
            event="RESTORE_SALES_PROCESS",
            from_status="ARCHIVIERT",
            to_status=target_status,
            metadata={
                "restored_by_type": request.restored_by_type,
                "restored_by_id": request.restored_by_id or "",
            },
        )
        self._store[process_id] = restored
        self._persist()
        return restored

    def generate_proposal(
        self,
        process_id: str,
        request: ProposalDocumentRequest,
    ) -> GeneratedDocumentResponse:
        process = self._store[process_id]
        if self._is_locked(process):
            raise HTTPException(status_code=409, detail="Der Vertriebsvorgang ist nach Antragserstellung gesperrt.")

        next_status = status_engine_service.apply_event(
            process.status_engine_version,
            process.status,
            "GENERATE_PROPOSAL",
        )
        updated = self._with_status(process, next_status)
        updated = self._append_history(
            updated,
            event="GENERATE_PROPOSAL",
            from_status=process.status,
            to_status=next_status,
            metadata={"proposal_type": request.proposal_type},
        )
        self._store[process_id] = updated
        artifact = document_output_service.get_config("v1")
        proposal_profile = artifact.proposal
        proposal_version = (
            len([doc for doc in updated.generated_documents if doc.document_kind == "PROPOSAL"]) + 1
        )
        generated_at = self._timestamp()
        file_name = f"{process_id}-{request.proposal_type.lower()}-proposal-v{proposal_version}.pdf"

        if proposal_profile.mode == "STATIC":
            input_snapshot: dict[str, object] = {}
            summary = {
                "documentIds": proposal_profile.staticConfig.documentIds,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *proposal_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *proposal_profile.staticConfig.documentIds,
                *proposal_profile.includedDocumentIds,
            ]
        elif proposal_profile.mode == "EXTERNAL":
            input_snapshot, generated_summary, _ = self._build_generated_input_snapshot(updated, "PROPOSAL")
            summary = {
                **generated_summary,
                "adapterId": proposal_profile.externalConfig.adapterId,
                "endpoint": proposal_profile.externalConfig.endpoint,
                "templateId": proposal_profile.externalConfig.templateId,
                "payloadMapping": proposal_profile.externalConfig.payloadMapping,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *proposal_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *self._all_available_document_ids(updated.canonical_state),
                *proposal_profile.includedDocumentIds,
            ]
        else:
            input_snapshot, generated_summary, _ = self._build_generated_input_snapshot(updated, "PROPOSAL")
            summary = {
                **generated_summary,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *proposal_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *self._all_available_document_ids(updated.canonical_state),
                *proposal_profile.includedDocumentIds,
            ]

        document = GeneratedDocumentRecord(
            id=f"{process_id}-proposal-{proposal_version}",
            document_kind="PROPOSAL",
            mode=proposal_profile.mode,
            variant=request.proposal_type,
            version_number=proposal_version,
            file_name=file_name,
            generated_at=generated_at,
            storage_reference=f"generated/{process_id}/{file_name}",
            summary=summary,
            required_documents=required_documents,
            input_snapshot=input_snapshot,
            source="SYSTEM",
            submission=DocumentSubmissionConfig(required=False, allowed=False, included=False),
        )
        if proposal_profile.mode == "EXTERNAL":
            external_summary, pdf_bytes = self._execute_external_document(
                updated,
                "PROPOSAL",
                file_name,
                request.proposal_type,
                proposal_profile.externalConfig.adapterId,
                proposal_profile.externalConfig.endpoint,
                proposal_profile.externalConfig.authType,
                proposal_profile.externalConfig.templateId,
                proposal_profile.externalConfig.payloadMapping,
                input_snapshot,
                summary,
            )
            document = document.model_copy(update={"summary": {**summary, **external_summary}})
        updated = updated.model_copy(
            update={
                "generated_documents": [*updated.generated_documents, document],
                "case_file": self._update_case_file_documents(updated, document),
            }
        )
        self._store[process_id] = updated
        if proposal_profile.mode == "EXTERNAL":
            self._write_document_bytes(document.storage_reference, pdf_bytes)
        else:
            self._write_generated_pdf(updated, document)
        self._persist()
        return self._build_response(updated, document)

    def generate_application(
        self,
        process_id: str,
        request: ApplicationDocumentRequest,
    ) -> GeneratedDocumentResponse:
        process = self._store[process_id]
        existing_application = self._latest_document(process, "APPLICATION")
        if existing_application is not None:
            return self._build_response(process, existing_application)

        next_status = status_engine_service.apply_event(
            process.status_engine_version,
            process.status,
            "GENERATE_APPLICATION",
        )
        updated = self._with_status(process, next_status)
        updated = self._append_history(
            updated,
            event="GENERATE_APPLICATION",
            from_status=process.status,
            to_status=next_status,
            metadata={"application_type": request.application_type},
        )
        artifact = document_output_service.get_config("v1")
        application_profile = artifact.application
        generated_at = self._timestamp()
        file_name = f"{process_id}-{request.application_type.lower()}-application.pdf"

        if application_profile.mode == "STATIC":
            input_snapshot: dict[str, object] = {}
            summary = {
                "documentIds": application_profile.staticConfig.documentIds,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *application_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *application_profile.staticConfig.documentIds,
                *application_profile.includedDocumentIds,
            ]
        elif application_profile.mode == "EXTERNAL":
            input_snapshot, generated_summary, _ = self._build_generated_input_snapshot(updated, "APPLICATION")
            summary = {
                **generated_summary,
                "adapterId": application_profile.externalConfig.adapterId,
                "endpoint": application_profile.externalConfig.endpoint,
                "templateId": application_profile.externalConfig.templateId,
                "payloadMapping": application_profile.externalConfig.payloadMapping,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *application_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *self._all_available_document_ids(updated.canonical_state),
                *application_profile.includedDocumentIds,
            ]
        else:
            input_snapshot, generated_summary, _ = self._build_generated_input_snapshot(updated, "APPLICATION")
            summary = {
                **generated_summary,
                "supportingDocuments": [
                    *self._all_available_document_ids(updated.canonical_state),
                    *application_profile.includedDocumentIds,
                ],
            }
            required_documents = [
                *self._all_available_document_ids(updated.canonical_state),
                *application_profile.includedDocumentIds,
            ]

        document = GeneratedDocumentRecord(
            id=f"{process_id}-application-1",
            document_kind="APPLICATION",
            mode=application_profile.mode,
            variant=request.application_type,
            version_number=1,
            file_name=file_name,
            generated_at=generated_at,
            storage_reference=f"generated/{process_id}/{file_name}",
            summary=summary,
            required_documents=required_documents,
            input_snapshot=input_snapshot,
            source="SYSTEM",
            submission=DocumentSubmissionConfig(required=True, allowed=True, included=True),
        )
        if application_profile.mode == "EXTERNAL":
            external_summary, pdf_bytes = self._execute_external_document(
                updated,
                "APPLICATION",
                file_name,
                request.application_type,
                application_profile.externalConfig.adapterId,
                application_profile.externalConfig.endpoint,
                application_profile.externalConfig.authType,
                application_profile.externalConfig.templateId,
                application_profile.externalConfig.payloadMapping,
                input_snapshot,
                summary,
            )
            document = document.model_copy(update={"summary": {**summary, **external_summary}})
        updated = updated.model_copy(
            update={
                "generated_documents": [*updated.generated_documents, document],
                "case_file": self._update_case_file_documents(updated, document),
            }
        )
        self._store[process_id] = updated
        if application_profile.mode == "EXTERNAL":
            self._write_document_bytes(document.storage_reference, pdf_bytes)
        else:
            self._write_generated_pdf(updated, document)
        self._persist()
        return self._build_response(updated, document)


sales_process_service = SalesProcessService()
