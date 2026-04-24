from __future__ import annotations

from app.core.config import settings
from app.domains.document_output.schemas import DocumentOutputArtifact, OutputManagementAdapter
from app.repositories.artifact_repository import ArtifactRepository


class DocumentOutputService:
    def __init__(self) -> None:
        self.repository = ArtifactRepository(settings.artifacts_root)

    def get_config(self, version: str) -> DocumentOutputArtifact:
        payload = self.repository.read_json("document_output", version, "config.json")
        return DocumentOutputArtifact.model_validate(payload)

    def save_config(self, version: str, artifact: DocumentOutputArtifact) -> DocumentOutputArtifact:
        self.repository.write_json(
            artifact.model_dump(mode="json"),
            "document_output",
            version,
            "config.json",
        )
        return artifact

    def delete_config(self, version: str) -> None:
        self.repository.delete("document_output", version, "config.json")

    def list_adapters(self) -> list[OutputManagementAdapter]:
        return [
            OutputManagementAdapter(
                id="OMS_WEBHOOK",
                label="Webhook Adapter",
                provider="Codex OMS",
                description="Allgemeiner HTTP-Adapter fuer externe Output-Management-Systeme.",
                protocol="HTTP",
                authTypes=["NONE", "BASIC", "BEARER", "API_KEY"],
                supportsPdf=True,
                status="ACTIVE",
            ),
            OutputManagementAdapter(
                id="OMS_MOCK",
                label="Mock Adapter",
                provider="Codex OMS",
                description="Testadapter fuer die kontrollierte Entwicklung von PDF- und OMS-Prozessen.",
                protocol="MOCK",
                authTypes=["NONE"],
                supportsPdf=True,
                status="ACTIVE",
            ),
        ]


document_output_service = DocumentOutputService()
