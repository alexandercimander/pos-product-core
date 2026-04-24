from __future__ import annotations

from app.core.config import settings
from app.domains.status_engine.schemas import StatusEngineArtifact
from app.repositories.artifact_repository import ArtifactRepository


class StatusEngineService:
    def __init__(self) -> None:
        self.repository = ArtifactRepository(settings.artifacts_root)

    def get_engine(self, version: str) -> StatusEngineArtifact:
        payload = self.repository.read_json("status_engine", version, "engine.json")
        return StatusEngineArtifact.model_validate(payload)

    def save_engine(
        self,
        version: str,
        artifact: StatusEngineArtifact,
    ) -> StatusEngineArtifact:
        self.repository.write_json(
            artifact.model_dump(mode="json"),
            "status_engine",
            version,
            "engine.json",
        )
        return artifact

    def delete_engine(self, version: str) -> None:
        self.repository.delete("status_engine", version, "engine.json")

    def apply_event(self, version: str, current_status: str, event: str) -> str:
        engine = self.get_engine(version)
        for transition in engine.transitions:
            if transition.from_status == current_status and transition.event == event:
                return transition.to_status
        return current_status


status_engine_service = StatusEngineService()

