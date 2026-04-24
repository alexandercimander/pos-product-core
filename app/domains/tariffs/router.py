from fastapi import APIRouter, Query

from app.domains.tariffs.schemas import (
    TariffCalculationAdapter,
    TariffCalculationBatchRequest,
    TariffCalculationBatchResponse,
    TariffCatalog,
)
from app.domains.tariffs.service import tariff_service


router = APIRouter()


@router.get("/{version}", response_model=TariffCatalog)
def get_tariff_catalog(version: str) -> TariffCatalog:
    return tariff_service.get_catalog(version)


@router.get("/adapters/list", response_model=list[TariffCalculationAdapter])
def list_tariff_calculation_adapters() -> list[TariffCalculationAdapter]:
    return tariff_service.list_calculation_adapters()


@router.post("/calculate", response_model=TariffCalculationBatchResponse)
def calculate_tariff(
    request: TariffCalculationBatchRequest,
    version: str = Query(default="latest"),
) -> TariffCalculationBatchResponse:
    return tariff_service.calculate_tariff_amounts(request, version=version)


@router.put("/{version}", response_model=TariffCatalog)
def save_tariff_catalog(version: str, catalog: TariffCatalog) -> TariffCatalog:
    return tariff_service.save_catalog(version, catalog)


@router.delete("/{version}")
def delete_tariff_catalog(version: str) -> dict[str, str]:
    tariff_service.delete_catalog(version)
    return {"status": "deleted"}
