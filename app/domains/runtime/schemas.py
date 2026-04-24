from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domains.flows.schemas import FlowDefinition
from app.domains.rules.schemas import RuleAction


class RuntimeProjection(BaseModel):
    flow: FlowDefinition
    current_step_index: int = 0
    state: dict[str, Any] = Field(default_factory=dict)
    pending_actions: list[RuleAction] = Field(default_factory=list)

