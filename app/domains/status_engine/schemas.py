from __future__ import annotations

from pydantic import BaseModel, Field


class StatusDefinition(BaseModel):
    code: str
    label: str
    description: str


class StatusTransition(BaseModel):
    id: str
    from_status: str
    event: str
    to_status: str
    label: str
    description: str


class StatusEngineArtifact(BaseModel):
    version: str
    initialStatus: str
    statuses: list[StatusDefinition] = Field(default_factory=list)
    transitions: list[StatusTransition] = Field(default_factory=list)

