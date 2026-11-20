from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql+psycopg2://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg2://" + value.removeprefix(
            "postgresql://"
        )
    return value


class Settings(BaseSettings):
    database_url: str = "sqlite:///./ledgerforge.db"
    data_dir: str = "../03_Data/csv"
    secret_key: str | None = None
    redis_url: str | None = None
    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg2_for_postgresql(cls, value: str) -> str:
        return normalize_database_url(value)


settings = Settings()
