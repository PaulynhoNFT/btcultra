from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql://signal_user:changeme@localhost:5432/signals"
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = "changeme-generate-secure-random-32-chars"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    totp_issuer: str = "SignalPlatform"

    # Environment
    environment: str = "development"

    # Exchange APIs
    binance_api_key: str = ""
    binance_api_secret: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""

    # News
    forex_factory_api_key: str = ""
    econoday_api_key: str = ""

    # Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    sendgrid_api_key: str = ""
    fcm_server_key: str = ""

    # S3/MinIO
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "signal-snapshots"

    # IPFS
    ipfs_api_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
