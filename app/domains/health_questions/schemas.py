from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


QuestionType = Literal[
    "BOOLEAN",
    "TEXT",
    "NUMBER",
    "DATE",
    "SINGLE_SELECT",
    "MULTI_SELECT",
    "DATE_RANGE",
]


class HealthQuestionConditions(BaseModel):
    tariffCategories: list[str]
    tariffIds: list[str]
    minAge: int
    maxAge: int


class HealthQuestionConditionRule(BaseModel):
    type: Literal["RULE"]
    questionId: str
    operator: Literal[
        "EQUALS",
        "NOT_EQUALS",
        "GREATER_THAN",
        "GREATER_OR_EQUAL",
        "LESS_THAN",
        "LESS_OR_EQUAL",
        "IS_SET",
    ]
    value: str | int | float | bool | list[str] | dict[str, str] | None = None
    answerType: QuestionType = "TEXT"


class HealthQuestionConditionAnd(BaseModel):
    type: Literal["AND"]
    conditions: list["HealthQuestionCondition"]


class HealthQuestionConditionOr(BaseModel):
    type: Literal["OR"]
    conditions: list["HealthQuestionCondition"]


class HealthQuestionConditionNot(BaseModel):
    type: Literal["NOT"]
    condition: "HealthQuestionCondition"


HealthQuestionCondition = Annotated[
    HealthQuestionConditionRule | HealthQuestionConditionAnd | HealthQuestionConditionOr | HealthQuestionConditionNot,
    Field(discriminator="type"),
]


class HealthQuestionDefinition(BaseModel):
    id: str
    label: str
    type: QuestionType
    detailLabel: str
    options: list[str] = []
    datePrecision: Literal["DAY", "MONTH", "YEAR"] = "DAY"
    parentQuestionId: str | None = None
    visibilityCondition: HealthQuestionCondition | None = None
    conditions: HealthQuestionConditions


class HealthQuestionCatalog(BaseModel):
    version: str
    questions: list[HealthQuestionDefinition]


class ResolveHealthQuestionsRequest(BaseModel):
    tariffIds: list[str] = Field(default_factory=list)
    insuranceStart: str | None = None
    birthDate: str | None = None


class ResolvedHealthQuestion(BaseModel):
    id: str
    label: str
    type: QuestionType
    detailLabel: str
    options: list[str] = Field(default_factory=list)
    datePrecision: Literal["DAY", "MONTH", "YEAR"] = "DAY"
    parentQuestionId: str | None = None
    visibilityCondition: HealthQuestionCondition | None = None
    conditions: HealthQuestionConditions
    sortOrder: int


class ResolveHealthQuestionsResponse(BaseModel):
    version: str
    insuranceStart: str | None = None
    birthDate: str | None = None
    ageAtInsuranceStart: int | None = None
    tariffIds: list[str] = Field(default_factory=list)
    tariffCategories: list[str] = Field(default_factory=list)
    questions: list[ResolvedHealthQuestion] = Field(default_factory=list)


HealthQuestionConditionAnd.model_rebuild()
HealthQuestionConditionOr.model_rebuild()
HealthQuestionConditionNot.model_rebuild()
