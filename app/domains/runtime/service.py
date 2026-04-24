from __future__ import annotations

from app.domains.flows.service import flow_service
from app.domains.rules.schemas import RuleEvaluationRequest
from app.domains.rules.service import rule_service
from app.domains.runtime.schemas import RuntimeProjection
from app.domains.sales_process.schemas import SalesProcess


class RuntimeService:
    def build_projection(self, process: SalesProcess) -> RuntimeProjection:
        flow = flow_service.get_flow(process.flow_id, process.flow_version)
        evaluation = rule_service.evaluate(
            "v1",
            RuleEvaluationRequest(
                event="onStepEnter",
                state=process.canonical_state,
            ),
        )
        return RuntimeProjection(
            flow=flow,
            state=process.canonical_state,
            pending_actions=evaluation.actions,
        )


runtime_service = RuntimeService()

