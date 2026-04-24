from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TariffCategory = Literal[
    "KOMPAKT",
    "AMBULANT",
    "STATIONAER",
    "ZAHN",
    "KRANKENTAGEGELD",
    "KRANKENHAUSTAGEGELD",
    "PFLEGETAGEGELD",
    "PFLEGEPFLICHT",
    "AUSLANDSREISEKRANKEN",
    "BEITRAGSENTLASTUNG",
    "SONSTIGES",
]

TariffType = Literal[
    "EINMALBEITRAG",
    "KV",
    "PPV",
    "ZUSATZTARIF",
    "GKV_ZUSATZVERSICHERUNG",
]

TariffGzuType = Literal["", "STANDARD"]

TariffCalculationMode = Literal["STATIC_AGE_BANDS", "FORMULA", "EXTERNAL"]
AuthType = Literal["NONE", "BASIC", "BEARER", "API_KEY"]


class TariffLevelBand(BaseModel):
    minLevel: float
    maxLevel: float
    payablePrice: float


class TariffAgeBand(BaseModel):
    minAge: int
    maxAge: int
    payablePrice: float
    levelBands: list[TariffLevelBand] = Field(default_factory=list)


class TariffAmountBand(BaseModel):
    minAge: int
    maxAge: int
    amount: float


class TariffFormulaConfig(BaseModel):
    expression: str = ""
    bindings: list[str] = Field(default_factory=list)


class TariffExternalConfig(BaseModel):
    adapterId: str = ""
    endpoint: str = ""
    authType: AuthType = "NONE"
    payloadMapping: str = ""
    previewValue: float = 0


class TariffCostCalculation(BaseModel):
    mode: TariffCalculationMode = "STATIC_AGE_BANDS"
    ageBands: list[TariffAmountBand] = Field(default_factory=list)
    formulaConfig: TariffFormulaConfig = Field(default_factory=TariffFormulaConfig)
    externalConfig: TariffExternalConfig = Field(default_factory=TariffExternalConfig)


class TariffCostComponents(BaseModel):
    acquisitionAndDistributionOneTime: TariffCostCalculation = Field(
        default_factory=TariffCostCalculation
    )
    acquisitionAndDistributionMonthly: TariffCostCalculation = Field(
        default_factory=TariffCostCalculation
    )
    administrationConsultingAndSupportMonthly: TariffCostCalculation = Field(
        default_factory=TariffCostCalculation
    )


class TariffCompatibilityConfig(BaseModel):
    incompatibleCategories: list[TariffCategory] = Field(default_factory=list)
    incompatibleTariffIds: list[str] = Field(default_factory=list)
    excludeSelfEmployedTariffs: bool = False
    excludeTrainingVariantTariffs: bool = False
    excludeAidTariffs: bool = False
    excludeDoctorTariffs: bool = False


class ContributionDevelopmentRow(BaseModel):
    policyYear: int
    attainedAge: int
    payablePrice: float


class ContributionDevelopmentConfig(BaseModel):
    referenceEntryAge: int = 35
    startYear: int = 2016
    endYear: int = 2026
    rows: list[ContributionDevelopmentRow] = Field(default_factory=list)


class TariffCalculationAdapter(BaseModel):
    id: str
    label: str
    provider: str
    description: str
    protocol: Literal["HTTP", "MOCK"]
    status: Literal["ACTIVE", "BETA", "UNAVAILABLE"]


class TariffDefinition(BaseModel):
    id: str
    externalName: str
    internalName: str
    category: TariffCategory
    tariffType: TariffType = "KV"
    validFrom: str = ""
    validUntil: str = ""
    sortOrder: int = 0
    maximumAge: int | None = None
    hasLegalSurcharge: bool = False
    gzuType: TariffGzuType = ""
    isDoctorTariff: bool = False
    isEligibleForAid: bool = False
    isSelfEmployedTariff: bool = False
    hasAgeingReserve: bool = False
    isTrainingVariant: bool = False
    hasLevels: bool = False
    minLevel: float | None = None
    maxLevel: float | None = None
    levelStep: float | None = None
    defaultLevel: float | None = None
    shortDescription: str
    longDescription: str
    monthlyPrice: float
    calculationMode: TariffCalculationMode = "STATIC_AGE_BANDS"
    ageBands: list[TariffAgeBand] = Field(default_factory=list)
    formulaConfig: TariffFormulaConfig = Field(default_factory=TariffFormulaConfig)
    externalConfig: TariffExternalConfig = Field(default_factory=TariffExternalConfig)
    compatibility: TariffCompatibilityConfig = Field(default_factory=TariffCompatibilityConfig)
    costs: TariffCostComponents = Field(default_factory=TariffCostComponents)
    contributionDevelopment: ContributionDevelopmentConfig = Field(
        default_factory=ContributionDevelopmentConfig
    )


class TariffCatalog(BaseModel):
    version: str
    tariffs: list[TariffDefinition]


class TariffCalculationRequest(BaseModel):
    tariffId: str
    canonicalState: dict[str, object] = Field(default_factory=dict)


class TariffCalculationResponse(BaseModel):
    tariffId: str
    amount: float
    source: Literal["LOCAL", "EXTERNAL"]
    adapterId: str = ""
    details: dict[str, object] = Field(default_factory=dict)


class TariffCalculationItemRequest(BaseModel):
    tariffId: str
    selectedLevel: float | None = None
    riskSurcharge: float = 0


class TariffCalculationBatchRequest(BaseModel):
    insuranceStart: str = Field(min_length=1)
    birthDate: str = Field(min_length=1)
    tariffs: list[TariffCalculationItemRequest] = Field(default_factory=list)
    canonicalState: dict[str, object] = Field(default_factory=dict)


class TariffContributionBreakdown(BaseModel):
    tariffContribution: float
    legalSurcharge: float
    riskSurcharge: float
    payablePrice: float
    additionalContributions: dict[str, float] = Field(default_factory=dict)


class TariffCalculationItemResponse(BaseModel):
    tariffId: str
    source: Literal["LOCAL", "EXTERNAL"]
    adapterId: str = ""
    contributions: TariffContributionBreakdown
    details: dict[str, object] = Field(default_factory=dict)


class TariffCalculationBatchResponse(BaseModel):
    items: list[TariffCalculationItemResponse] = Field(default_factory=list)
    availableContributions: list[str] = Field(
        default_factory=lambda: [
            "tariffContribution",
            "legalSurcharge",
            "riskSurcharge",
            "payablePrice",
        ]
    )
