from __future__ import annotations

import re

from app.core.config import settings
from app.domains.tariffs.calculation import calculate_age_at_date
from app.domains.health_questions.schemas import (
    HealthQuestionCatalog,
    ResolveHealthQuestionsResponse,
    ResolvedHealthQuestion,
)
from app.domains.tariffs.service import tariff_service
from app.repositories.artifact_repository import ArtifactRepository


class HealthQuestionService:
    def __init__(self) -> None:
        self.repository = ArtifactRepository(settings.artifacts_root)

    def _resolve_version(self, version: str) -> str:
        normalized = (version or "").strip().lower()
        if normalized != "latest":
            return version
        available_versions = self.repository.list_directories("health_questions")
        if not available_versions:
            return "v1"
        version_pattern = re.compile(r"^v(\d+)$", re.IGNORECASE)

        def version_key(value: str) -> tuple[int, str]:
            match = version_pattern.match(value)
            if match:
                return int(match.group(1)), value
            return -1, value

        return max(available_versions, key=version_key)

    def get_catalog(self, version: str) -> HealthQuestionCatalog:
        resolved_version = self._resolve_version(version)
        payload = self.repository.read_json("health_questions", resolved_version, "catalog.json")
        return HealthQuestionCatalog.model_validate(payload)

    def save_catalog(self, version: str, catalog: HealthQuestionCatalog) -> HealthQuestionCatalog:
        self.repository.write_json(
            catalog.model_dump(mode="json"),
            "health_questions",
            version,
            "catalog.json",
        )
        return catalog

    def resolve_by_tariffs(
        self,
        *,
        version: str,
        tariff_ids: list[str],
        insurance_start: str | None = None,
        birth_date: str | None = None,
    ) -> ResolveHealthQuestionsResponse:
        catalog = self.get_catalog(version)
        age_at_insurance_start = calculate_age_at_date(birth_date, insurance_start)
        if not tariff_ids:
            return ResolveHealthQuestionsResponse(
                version=version,
                insuranceStart=insurance_start,
                birthDate=birth_date,
                ageAtInsuranceStart=age_at_insurance_start,
                tariffIds=[],
                tariffCategories=[],
                questions=[],
            )

        tariff_catalog = tariff_service.get_catalog("v1")
        selected_tariffs = [tariff for tariff in tariff_catalog.tariffs if tariff.id in set(tariff_ids)]
        selected_categories = sorted({tariff.category for tariff in selected_tariffs})
        selected_tariff_ids = {tariff.id for tariff in selected_tariffs}
        deduped_questions: list[ResolvedHealthQuestion] = []
        seen_ids: set[str] = set()

        for index, question in enumerate(catalog.questions, start=1):
            condition_tariff_ids = set(question.conditions.tariffIds or [])
            condition_categories = set(question.conditions.tariffCategories or [])
            matches_tariff_id = bool(condition_tariff_ids & selected_tariff_ids)
            matches_category = bool(condition_categories & set(selected_categories))
            if not matches_tariff_id and not matches_category:
                continue
            if isinstance(age_at_insurance_start, int):
                min_age = int(question.conditions.minAge)
                max_age = int(question.conditions.maxAge)
                if age_at_insurance_start < min_age or age_at_insurance_start > max_age:
                    continue
            if question.id in seen_ids:
                continue
            seen_ids.add(question.id)
            deduped_questions.append(
                ResolvedHealthQuestion(
                    id=question.id,
                    label=question.label,
                    type=question.type,
                    detailLabel=question.detailLabel,
                    options=list(question.options or []),
                    datePrecision=question.datePrecision,
                    parentQuestionId=question.parentQuestionId,
                    visibilityCondition=question.visibilityCondition,
                    conditions=question.conditions,
                    sortOrder=index,
                )
            )

        return ResolveHealthQuestionsResponse(
            version=version,
            insuranceStart=insurance_start,
            birthDate=birth_date,
            ageAtInsuranceStart=age_at_insurance_start,
            tariffIds=tariff_ids,
            tariffCategories=selected_categories,
            questions=deduped_questions,
        )


health_question_service = HealthQuestionService()
