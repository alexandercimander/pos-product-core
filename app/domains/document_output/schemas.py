from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocumentOutputMode = Literal["STATIC", "GENERATED", "EXTERNAL"]
DocumentOutputInputType = Literal[
    "TEXT",
    "TEXTAREA",
    "DATE",
    "NUMBER",
    "CHECKBOX",
    "SELECT",
    "IMAGE",
    "SIGNATURE",
    "TARIFF_TABLE",
    "TARIFF_COST_TABLE",
    "CONTRIBUTION_DEVELOPMENT_TABLE",
]
SignatureRole = Literal[
    "",
    "INSURED_PERSON",
    "POLICY_HOLDER",
    "PAYMENT_CONTRIBUTOR",
    "INTERMEDIARY",
]
AuthType = Literal["NONE", "BASIC", "BEARER", "API_KEY"]


class DocumentOutputInput(BaseModel):
    id: str
    label: str
    type: DocumentOutputInputType
    binding: str = ""
    signatureRole: SignatureRole = ""
    editable: bool = False
    required: bool = False
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)


class DocumentOutputSection(BaseModel):
    id: str
    title: str
    description: str = ""
    inputs: list[DocumentOutputInput] = Field(default_factory=list)


class StaticDocumentOutputConfig(BaseModel):
    documentIds: list[str] = Field(default_factory=list)


class GeneratedDocumentOutputConfig(BaseModel):
    logoUrl: str = ""
    headerText: str = ""
    titleTemplate: str = ""
    notices: list[str] = Field(default_factory=list)
    includeTimestamp: bool = True
    includeSalesProcessId: bool = True
    sections: list[DocumentOutputSection] = Field(default_factory=list)


class ExternalDocumentOutputConfig(BaseModel):
    adapterId: str = ""
    endpoint: str = ""
    authType: AuthType = "NONE"
    templateId: str = ""
    payloadMapping: str = ""


class DocumentOutputProfile(BaseModel):
    mode: DocumentOutputMode = "GENERATED"
    availableFromStepId: str = ""
    requiredRuleIds: list[str] = Field(default_factory=list)
    requireAllMandatoryFields: bool = False
    includedDocumentIds: list[str] = Field(default_factory=list)
    staticConfig: StaticDocumentOutputConfig = Field(default_factory=StaticDocumentOutputConfig)
    generatedConfig: GeneratedDocumentOutputConfig = Field(default_factory=GeneratedDocumentOutputConfig)
    externalConfig: ExternalDocumentOutputConfig = Field(default_factory=ExternalDocumentOutputConfig)


class OutputManagementAdapter(BaseModel):
    id: str
    label: str
    provider: str
    description: str
    protocol: Literal["HTTP", "MOCK"]
    authTypes: list[AuthType] = Field(default_factory=list)
    supportsPdf: bool = True
    status: Literal["ACTIVE", "BETA", "UNAVAILABLE"] = "ACTIVE"


class DocumentOutputArtifact(BaseModel):
    version: str
    proposal: DocumentOutputProfile = Field(default_factory=DocumentOutputProfile)
    application: DocumentOutputProfile = Field(default_factory=DocumentOutputProfile)
