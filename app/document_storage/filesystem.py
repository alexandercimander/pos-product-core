from __future__ import annotations

from pathlib import Path

from app.document_storage.base import DocumentStorage


class FilesystemDocumentStorage(DocumentStorage):
    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve_path(self, storage_reference: str) -> Path:
        return self.root / storage_reference

    def write_bytes(
        self,
        storage_reference: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        del content_type
        target = self._resolve_path(storage_reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def exists(self, storage_reference: str) -> bool:
        return self._resolve_path(storage_reference).exists()

    def materialize(
        self,
        storage_reference: str,
        *,
        filename_hint: str | None = None,
    ) -> Path:
        del filename_hint
        return self._resolve_path(storage_reference)
