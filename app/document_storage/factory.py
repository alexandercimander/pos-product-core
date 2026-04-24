from __future__ import annotations

from app.core.config import Settings
from app.document_storage.azure_blob import AzureBlobDocumentStorage
from app.document_storage.base import DocumentStorage
from app.document_storage.filesystem import FilesystemDocumentStorage


def build_document_storage(settings: Settings) -> DocumentStorage:
    provider = settings.document_storage_provider.strip().lower()
    if provider == "azure_blob":
        return AzureBlobDocumentStorage(
            connection_string=settings.document_storage_azure_connection_string,
            container_name=settings.document_storage_azure_container,
            cache_root=settings.document_storage_cache_root,
        )
    return FilesystemDocumentStorage(settings.storage_root)
