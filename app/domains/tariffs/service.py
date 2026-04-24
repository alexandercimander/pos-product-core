from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from app.core.bindings import resolve_binding
from app.core.external_http import post_json
from app.core.config import settings
from app.domains.tariffs.calculation import (
    calculate_cost_amount,
    calculate_tariff_payable_price,
    calculate_tariff_price,
    derive_tariff_contribution_from_payable,
    calculate_age_at_date,
)
from app.domains.tariffs.schemas import (
    TariffCalculationAdapter,
    TariffCalculationBatchRequest,
    TariffCalculationBatchResponse,
    TariffCalculationItemResponse,
    TariffCalculationRequest,
    TariffCalculationResponse,
    TariffContributionBreakdown,
    TariffCatalog,
    TariffCostCalculation,
    TariffDefinition,
)
from app.repositories.artifact_repository import ArtifactRepository


class TariffService:
    def __init__(self) -> None:
        self.repository = ArtifactRepository(settings.artifacts_root)

    def _resolve_version(self, version: str) -> str:
        normalized = (version or "").strip().lower()
        if normalized != "latest":
            return version
        available_versions = self.repository.list_directories("tariffs")
        if not available_versions:
            raise HTTPException(status_code=404, detail="Kein Tarifkatalog verfügbar.")
        version_pattern = re.compile(r"^v(\d+)$", re.IGNORECASE)

        def version_key(value: str) -> tuple[int, str]:
            match = version_pattern.match(value)
            if match:
                return int(match.group(1)), value
            return -1, value

        return max(available_versions, key=version_key)

    def get_catalog(self, version: str) -> TariffCatalog:
        resolved_version = self._resolve_version(version)
        payload = self.repository.read_json("tariffs", resolved_version, "catalog.json")
        return TariffCatalog.model_validate(payload)

    def save_catalog(self, version: str, catalog: TariffCatalog) -> TariffCatalog:
        self.repository.write_json(
            catalog.model_dump(mode="json"),
            "tariffs",
            version,
            "catalog.json",
        )
        return catalog

    def delete_catalog(self, version: str) -> None:
        self.repository.delete("tariffs", version, "catalog.json")

    def list_calculation_adapters(self) -> list[TariffCalculationAdapter]:
        return [
            TariffCalculationAdapter(
                id="TARIFF_CALCULATION_MOCK",
                label="Mock-Rechenkern",
                provider="Codex Tarif",
                description="Stellt einen konfigurierbaren Beispieladapter fuer externe Rechenkerne bereit.",
                protocol="MOCK",
                status="ACTIVE",
            ),
            TariffCalculationAdapter(
                id="TARIFF_CALCULATION_WEBHOOK",
                label="Webhook-Rechenkern",
                provider="Codex Tarif",
                description="Allgemeiner HTTP-Adapter fuer externe Rechenkerne.",
                protocol="HTTP",
                status="BETA",
            ),
        ]

    def _resolve_external_amount(
        self,
        tariff: TariffDefinition,
        external_config: Any,
        canonical_state: dict[str, object],
        calculation_context: str,
    ) -> tuple[float, dict[str, object]]:
        if external_config.adapterId == "TARIFF_CALCULATION_MOCK":
            age = calculate_age_at_date(
                resolve_binding(canonical_state, "insuredPersons[active].person.birthDate"),
                resolve_binding(canonical_state, "applicationStart"),
            )
            selected_level = resolve_binding(
                canonical_state,
                f"insuredPersons[active].tariffSelection.selectedLevels.{tariff.id}",
            )
            if not isinstance(selected_level, (int, float)):
                selected_level = (
                    tariff.defaultLevel if tariff.defaultLevel is not None else tariff.minLevel
                )
            if tariff.hasLevels and isinstance(selected_level, (int, float)) and isinstance(age, int):
                amount = max(0.0, (float(selected_level) / 100.0) * age)
            else:
                amount = float(external_config.previewValue or tariff.monthlyPrice or 0)
            return amount, {
                "adapterId": external_config.adapterId,
                "mode": "MOCK",
                "context": calculation_context,
            }

        payload = {
            "adapterId": external_config.adapterId,
            "tariffId": tariff.id,
            "context": calculation_context,
            "payloadMapping": external_config.payloadMapping,
            "canonicalState": canonical_state,
            "tariff": tariff.model_dump(mode="json"),
        }
        response = post_json(external_config.endpoint, payload, external_config.authType)
        result = response.json()
        for key in ("amount", "payablePrice", "value"):
            if key in result:
                return float(result[key] or 0), {
                    "adapterId": external_config.adapterId,
                    "mode": "HTTP",
                    "context": calculation_context,
                    "response": result,
                }
        raise HTTPException(
            status_code=502,
            detail="Externe Tarifkalkulation muss 'amount', 'payablePrice' oder 'value' liefern.",
        )

    def calculate_tariff_amount(
        self,
        request: TariffCalculationRequest,
        version: str = "v1",
    ) -> TariffCalculationResponse:
        catalog = self.get_catalog(version)
        tariff = next((item for item in catalog.tariffs if item.id == request.tariffId), None)
        if tariff is None:
            raise HTTPException(status_code=404, detail=f"Tarif {request.tariffId} wurde nicht gefunden.")

        if tariff.calculationMode == "EXTERNAL":
            amount, details = self._resolve_external_amount(
                tariff,
                tariff.externalConfig,
                request.canonicalState,
                "TARIFF_PRICE",
            )
            return TariffCalculationResponse(
                tariffId=tariff.id,
                amount=max(0.0, derive_tariff_contribution_from_payable(
                    tariff,
                    amount,
                    request.canonicalState,
                    catalog.tariffs,
                )),
                source="EXTERNAL",
                adapterId=tariff.externalConfig.adapterId,
                details={**details, "payableAmount": max(0.0, amount)},
            )

        amount = calculate_tariff_price(tariff, request.canonicalState, catalog.tariffs)
        return TariffCalculationResponse(
            tariffId=tariff.id,
            amount=max(0.0, amount),
            source="LOCAL",
            details={"context": "TARIFF_PRICE"},
        )

    def _build_batch_canonical_state(
        self,
        request: TariffCalculationBatchRequest,
    ) -> dict[str, object]:
        base_state = dict(request.canonicalState or {})
        base_state["applicationStart"] = request.insuranceStart

        insured_persons = base_state.get("insuredPersons")
        insured_persons_list: list[dict[str, object]]
        if isinstance(insured_persons, list):
            insured_persons_list = [dict(entry) for entry in insured_persons if isinstance(entry, dict)]
        else:
            insured_persons_list = []

        if not insured_persons_list:
            insured_persons_list = [
                {
                    "insuredPersonId": "insured-person-1",
                    "person": {},
                    "health": {"questionnaire": {"availableQuestionIds": [], "responses": []}},
                    "tariffSelection": {},
                    "documents": {"available": []},
                }
            ]
        active_index = 0
        if isinstance(base_state.get("runtimeContext"), dict):
            raw_index = base_state["runtimeContext"].get("activeInsuredPersonIndex")
            if isinstance(raw_index, int) and 0 <= raw_index < len(insured_persons_list):
                active_index = raw_index
        active_person = dict(insured_persons_list[active_index])
        person_data = dict(active_person.get("person") if isinstance(active_person.get("person"), dict) else {})
        person_data["birthDate"] = request.birthDate
        active_person["person"] = person_data

        tariff_selection = dict(
            active_person.get("tariffSelection")
            if isinstance(active_person.get("tariffSelection"), dict)
            else {}
        )
        selected_levels = dict(
            tariff_selection.get("selectedLevels")
            if isinstance(tariff_selection.get("selectedLevels"), dict)
            else {}
        )
        risk_surcharges = dict(
            tariff_selection.get("riskSurcharges")
            if isinstance(tariff_selection.get("riskSurcharges"), dict)
            else {}
        )
        selected_tariffs: list[str] = []
        for item in request.tariffs:
            selected_tariffs.append(item.tariffId)
            if item.selectedLevel is not None:
                selected_levels[item.tariffId] = float(item.selectedLevel)
            risk_surcharges[item.tariffId] = float(item.riskSurcharge or 0)
        tariff_selection["selectedTariffs"] = selected_tariffs
        tariff_selection["selectedLevels"] = selected_levels
        tariff_selection["riskSurcharges"] = risk_surcharges
        active_person["tariffSelection"] = tariff_selection
        insured_persons_list[active_index] = active_person
        base_state["insuredPersons"] = insured_persons_list
        base_state["runtimeContext"] = {
            **(
                base_state.get("runtimeContext")
                if isinstance(base_state.get("runtimeContext"), dict)
                else {}
            ),
            "activeInsuredPersonIndex": active_index,
        }
        return base_state

    def calculate_tariff_amounts(
        self,
        request: TariffCalculationBatchRequest,
        version: str = "v1",
    ) -> TariffCalculationBatchResponse:
        if not request.tariffs:
            raise HTTPException(status_code=422, detail="Mindestens ein Tarif muss angegeben werden.")

        catalog = self.get_catalog(version)
        tariffs_by_id = {tariff.id: tariff for tariff in catalog.tariffs}
        canonical_state = self._build_batch_canonical_state(request)
        items: list[TariffCalculationItemResponse] = []

        for tariff_request in request.tariffs:
            tariff = tariffs_by_id.get(tariff_request.tariffId)
            if tariff is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Tarif {tariff_request.tariffId} wurde nicht gefunden.",
                )
            risk_surcharge = max(0.0, float(tariff_request.riskSurcharge or 0))
            if tariff.calculationMode == "EXTERNAL":
                payable_without_risk, details = self._resolve_external_amount(
                    tariff,
                    tariff.externalConfig,
                    canonical_state,
                    "TARIFF_PRICE",
                )
                source = "EXTERNAL"
                adapter_id = tariff.externalConfig.adapterId
            else:
                payable_without_risk = calculate_tariff_payable_price(
                    tariff,
                    canonical_state,
                    catalog.tariffs,
                )
                details = {"context": "TARIFF_PRICE", "mode": "LOCAL"}
                source = "LOCAL"
                adapter_id = ""
            tariff_contribution = max(
                0.0,
                derive_tariff_contribution_from_payable(
                    tariff,
                    payable_without_risk,
                    canonical_state,
                    catalog.tariffs,
                ),
            )
            legal_surcharge = max(0.0, payable_without_risk - tariff_contribution)
            items.append(
                TariffCalculationItemResponse(
                    tariffId=tariff.id,
                    source=source,
                    adapterId=adapter_id,
                    contributions=TariffContributionBreakdown(
                        tariffContribution=round(tariff_contribution, 2),
                        legalSurcharge=round(legal_surcharge, 2),
                        riskSurcharge=round(risk_surcharge, 2),
                        payablePrice=round(max(0.0, payable_without_risk + risk_surcharge), 2),
                    ),
                    details={
                        **details,
                        "payableWithoutRisk": round(max(0.0, payable_without_risk), 2),
                    },
                )
            )

        return TariffCalculationBatchResponse(items=items)

    def calculate_cost_component_amount(
        self,
        tariff: TariffDefinition,
        calculation: TariffCostCalculation,
        fallback_value: float,
        canonical_state: dict[str, object],
        tariffs: list[TariffDefinition],
        calculation_context: str,
    ) -> tuple[float, dict[str, object]]:
        if calculation.mode == "EXTERNAL":
            amount, details = self._resolve_external_amount(
                tariff,
                calculation.externalConfig,
                canonical_state,
                calculation_context,
            )
            return max(0.0, amount), details

        return (
            max(0.0, calculate_cost_amount(calculation, fallback_value, canonical_state, tariffs)),
            {"context": calculation_context, "mode": "LOCAL"},
        )


tariff_service = TariffService()
