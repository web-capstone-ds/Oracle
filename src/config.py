from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_client_id: str = "ds_oracle_001"
    mqtt_username: str = "oracle"
    mqtt_password: str = "oracle_secret"
    mqtt_keepalive_sec: int = 60
    mqtt_session_expiry_sec: int = 3600

    oracle_db_host: str = "localhost"
    oracle_db_port: int = 5433
    oracle_db_name: str = "oracle"
    oracle_db_user: str = "oracle"
    oracle_db_password: str = "oracle_secret"
    oracle_db_pool_min: int = 1
    oracle_db_pool_max: int = 5

    historian_db_host: str = "localhost"
    historian_db_port: int = 5432
    historian_db_name: str = "historian"
    historian_db_user: str = "oracle_reader"
    historian_db_password: str = "reader_secret"
    historian_db_pool_min: int = 1
    historian_db_pool_max: int = 5

    rule_cache_ttl_sec: int = 300
    shutdown_timeout_sec: float = 5.0

    log_level: str = "INFO"
    log_format: str = Field(default="json", pattern="^(json|console)$")

    @property
    def oracle_dsn(self) -> str:
        return (
            f"host={self.oracle_db_host} port={self.oracle_db_port} "
            f"dbname={self.oracle_db_name} user={self.oracle_db_user} "
            f"password={self.oracle_db_password}"
        )

    @property
    def historian_dsn(self) -> str:
        return (
            f"host={self.historian_db_host} port={self.historian_db_port} "
            f"dbname={self.historian_db_name} user={self.historian_db_user} "
            f"password={self.historian_db_password}"
        )


settings = Settings()
