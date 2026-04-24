from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_artifacts_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    local_artifacts = repo_root / "artifacts"
    if local_artifacts.exists():
        return local_artifacts
    builder_artifacts = repo_root.parent / "PoSBuilder" / "artifacts"
    return builder_artifacts


class Settings(BaseSettings):
    app_name: str = "PoS Product Core"
    app_version: str = "0.1.0"
    artifacts_root: Path = _default_artifacts_root()
    storage_root: Path = Path(__file__).resolve().parents[2] / "storage"
    document_storage_provider: str = "filesystem"
    document_storage_cache_root: Path = Path(__file__).resolve().parents[2] / "tmp"
    document_storage_azure_connection_string: str = ""
    document_storage_azure_container: str = "documents"
    database_url: str = "sqlite:///./pos-product-core.db"
    database_auto_create_tables: bool = True
    external_request_timeout_seconds: int = 10
    external_basic_username: str = ""
    external_basic_password: str = ""
    external_bearer_token: str = ""
    external_api_key_header: str = "X-API-Key"
    external_api_key_value: str = ""

    model_config = SettingsConfigDict(env_prefix="POS_CORE_", extra="ignore")


settings = Settings()
