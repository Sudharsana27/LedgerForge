from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./ledgerforge.db"
    data_dir: str = "../03_Data/csv"
    secret_key: str | None = None
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
