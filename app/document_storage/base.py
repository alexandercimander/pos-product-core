from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentStorage(ABC):
    @abstractmethod
    def write_bytes(
        self,
        storage_reference: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Persist raw document bytes under the given storage reference."""

    @abstractmethod
    def exists(self, storage_reference: str) -> bool:
        """Check whether a document already exists in the backing store."""

    @abstractmethod
    def materialize(
        self,
        storage_reference: str,
        *,
        filename_hint: str | None = None,
    ) -> Path:
        """Return a local path that can be streamed back to callers."""
