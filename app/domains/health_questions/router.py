from fastapi import APIRouter, Query

from app.domains.health_questions.schemas import (
    HealthQuestionCatalog,
    ResolveHealthQuestionsRequest,
    ResolveHealthQuestionsResponse,
)
from app.domains.health_questions.service import health_question_service


router = APIRouter()


@router.get("/{version}", response_model=HealthQuestionCatalog)
def get_health_question_catalog(version: str) -> HealthQuestionCatalog:
    return health_question_service.get_catalog(version)


@router.put("/{version}", response_model=HealthQuestionCatalog)
def save_health_question_catalog(
    version: str,
    catalog: HealthQuestionCatalog,
) -> HealthQuestionCatalog:
    return health_question_service.save_catalog(version, catalog)


@router.post("/{version}/resolve", response_model=ResolveHealthQuestionsResponse)
def resolve_health_questions(
    version: str,
    request: ResolveHealthQuestionsRequest,
) -> ResolveHealthQuestionsResponse:
    return health_question_service.resolve_by_tariffs(
        version=version,
        tariff_ids=request.tariffIds,
        insurance_start=request.insuranceStart,
        birth_date=request.birthDate,
    )


@router.post("/resolve", response_model=ResolveHealthQuestionsResponse)
def resolve_health_questions_without_version(
    request: ResolveHealthQuestionsRequest,
    version: str = Query(default="latest"),
) -> ResolveHealthQuestionsResponse:
    return health_question_service.resolve_by_tariffs(
        version=version,
        tariff_ids=request.tariffIds,
        insurance_start=request.insuranceStart,
        birth_date=request.birthDate,
    )
