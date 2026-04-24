from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PoS Product Core"
    app_version: str = "0.1.0"
    artifacts_root: Path = Path(__file__).resolve().parents[3] / "artifacts"
    storage_root: Path = Path(__file__).resolve().parents[3] / "storage"
    database_url: str = "sqlite:///./pos-product-core.db"
    external_request_timeout_seconds: int = 10
    external_basic_username: str = ""
    external_basic_password: str = ""
    external_bearer_token: str = ""
    external_api_key_header: str = "X-API-Key"
    external_api_key_value: str = ""

    model_config = SettingsConfigDict(env_prefix="POS_CORE_", extra="ignore")


settings = Settings()
