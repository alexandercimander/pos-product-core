from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ArtifactEnvelope(BaseModel):
    version: str
    content: dict[str, Any] = Field(default_factory=dict)


class JsonDocument(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)

