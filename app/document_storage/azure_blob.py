from __future__ import annotations

from pathlib import Path

from app.document_storage.base import DocumentStorage


class AzureBlobDocumentStorage(DocumentStorage):
    def __init__(
        self,
        *,
        connection_string: str,
        container_name: str,
        cache_root: Path,
    ) -> None:
        if not connection_string:
            raise ValueError(
                "POS_CORE_DOCUMENT_STORAGE_AZURE_CONNECTION_STRING muss gesetzt sein, "
                "wenn azure_blob als Document Storage verwendet wird."
            )
        self.connection_string = connection_string
        self.container_name = container_name
        self.cache_root = cache_root / "blob-cache"

    def _blob_client(self, storage_reference: str):
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(self.connection_string)
        container = service.get_container_client(self.container_name)
        return container.get_blob_client(storage_reference)

    def write_bytes(
        self,
        storage_reference: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        from azure.storage.blob import ContentSettings

        client = self._blob_client(storage_reference)
        client.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def exists(self, storage_reference: str) -> bool:
        return self._blob_client(storage_reference).exists()

    def materialize(
        self,
        storage_reference: str,
        *,
        filename_hint: str | None = None,
    ) -> Path:
        target_name = filename_hint or Path(storage_reference).name
        target = self.cache_root / storage_reference
        if target_name and target.name != target_name:
            target = target.with_name(target_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            downloader = self._blob_client(storage_reference).download_blob()
            target.write_bytes(downloader.readall())
        return target
