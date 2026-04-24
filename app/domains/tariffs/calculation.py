from __future__ import annotations

import re
from typing import Any

from app.core.bindings import resolve_binding
from app.domains.tariffs.schemas import (
    TariffCostCalculation,
    TariffDefinition,
)


def calculate_age_at_date(birth_date: str | None, target_date: str | None) -> int | None:
    if not birth_date or not target_date:
        return None

    try:
        birth_year, birth_month, birth_day = [int(part) for part in birth_date.split("-")]
        target_year, target_month, target_day = [int(part) for part in target_date.split("-")]
    except (TypeError, ValueError):
        return None

    age = target_year - birth_year
    before_birthday = (target_month, target_day) < (birth_month, birth_day)
    return age - 1 if before_birthday else age


def build_tariff_facts(state: dict[str, Any], tariffs: list[TariffDefinition]) -> dict[str, Any]:
    selected_ids = resolve_binding(state, "insuredPersons[active].tariffSelection.selectedTariffs") or []
    selected_categories = [
        tariff.category
        for tariff in tariffs
        if tariff.id in selected_ids
    ]
    birth_date = resolve_binding(state, "insuredPersons[active].person.birthDate")
    application_start = resolve_binding(state, "applicationStart")
    return {
        **state,
        "meta": {
            "ageAtInsuranceStart": calculate_age_at_date(birth_date, application_start),
            "selectedTariffCategories": selected_categories,
        },
    }


def _get_selected_tariff_level(tariff: TariffDefinition, state: dict[str, Any]) -> float | None:
    selected_level = resolve_binding(
        state,
        f"insuredPersons[active].tariffSelection.selectedLevels.{tariff.id}",
    )
    if isinstance(selected_level, (int, float)):
        return float(selected_level)
    if tariff.defaultLevel is not None:
        return float(tariff.defaultLevel)
    if tariff.minLevel is not None:
        return float(tariff.minLevel)
    return None


def _normalize_formula_expression(expression: str) -> str:
    normalized = expression.replace("&&", " and ").replace("||", " or ")
    normalized = re.sub(r"\bUND\b", " and ", normalized, flags=re.IGNORECASE)
    return re.sub(r"\bODER\b", " or ", normalized, flags=re.IGNORECASE)


def _resolve_formula_references(expression: str, facts: dict[str, Any]) -> str:
    def replacer(match: re.Match[str]) -> str:
        binding = match.group(1).strip()
        value = resolve_binding(facts, binding)
        if value in (None, ""):
            return "0"
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return str(value)
        return repr(value)

    return re.sub(r"\{\{([^}]+)\}\}", replacer, expression)


def _evaluate_formula(expression: str, facts: dict[str, Any]) -> float | None:
    resolved = _normalize_formula_expression(_resolve_formula_references(expression, facts)).strip()
    if not resolved:
        return None

    def if_fn(condition: Any, when_true: Any, when_false: Any) -> Any:
        return when_true if condition else when_false

    def case_fn(*args: Any) -> Any:
        for index in range(0, len(args) - 1, 2):
            if args[index]:
                return args[index + 1]
        return args[-1] if len(args) % 2 == 1 else 0

    try:
        result = eval(
            resolved,
            {"__builtins__": {}},
            {"IF": if_fn, "CASE": case_fn},
        )
    except Exception:
        return None

    try:
        return float(result)
    except (TypeError, ValueError):
        return None


def calculate_tariff_price(
    tariff: TariffDefinition,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> float:
    payable_without_risk = calculate_tariff_payable_price(tariff, state, tariffs)
    return derive_tariff_contribution_from_payable(
        tariff, payable_without_risk, state, tariffs
    )


def _is_standard_legal_surcharge_applicable(
    tariff: TariffDefinition,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> bool:
    if not tariff.hasLegalSurcharge or tariff.gzuType != "STANDARD":
        return False
    facts = build_tariff_facts(state, tariffs)
    age = resolve_binding(facts, "meta.ageAtInsuranceStart")
    return isinstance(age, int) and 22 <= age <= 60


def calculate_tariff_payable_price(
    tariff: TariffDefinition,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> float:
    facts = build_tariff_facts(state, tariffs)

    if tariff.calculationMode == "STATIC_AGE_BANDS":
        age = resolve_binding(facts, "meta.ageAtInsuranceStart")
        selected_level = _get_selected_tariff_level(tariff, state) if tariff.hasLevels else None
        for band in tariff.ageBands:
            if isinstance(age, int) and band.minAge <= age <= band.maxAge:
                if band.levelBands and selected_level is not None:
                    for level_band in band.levelBands:
                        if level_band.minLevel <= selected_level <= level_band.maxLevel:
                            return max(0.0, level_band.payablePrice)
                return max(0.0, band.payablePrice)
        return max(0.0, tariff.monthlyPrice)

    if tariff.calculationMode == "FORMULA":
        result = _evaluate_formula(tariff.formulaConfig.expression, facts)
        return max(0.0, result if result is not None else tariff.monthlyPrice)

    return max(0.0, tariff.externalConfig.previewValue or tariff.monthlyPrice)


def calculate_legal_surcharge_amount(
    tariff: TariffDefinition,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> float:
    payable_without_risk = calculate_tariff_payable_price(tariff, state, tariffs)
    tariff_price = calculate_tariff_price(tariff, state, tariffs)
    return max(0.0, payable_without_risk - tariff_price)


def derive_tariff_contribution_from_payable(
    tariff: TariffDefinition,
    payable_without_risk: float,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> float:
    if _is_standard_legal_surcharge_applicable(tariff, state, tariffs):
        return max(0.0, payable_without_risk / 1.1)
    return max(0.0, payable_without_risk)


def calculate_cost_amount(
    calculation: TariffCostCalculation,
    fallback_value: float,
    state: dict[str, Any],
    tariffs: list[TariffDefinition],
) -> float:
    facts = build_tariff_facts(state, tariffs)

    if calculation.mode == "STATIC_AGE_BANDS":
        age = resolve_binding(facts, "meta.ageAtInsuranceStart")
        for band in calculation.ageBands:
            if isinstance(age, int) and band.minAge <= age <= band.maxAge:
                return max(0.0, band.amount)
        return max(0.0, fallback_value)

    if calculation.mode == "FORMULA":
        result = _evaluate_formula(calculation.formulaConfig.expression, facts)
        return max(0.0, result if result is not None else fallback_value)

    return max(0.0, calculation.externalConfig.previewValue or fallback_value)
