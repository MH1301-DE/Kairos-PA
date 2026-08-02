from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    kairos_kek: str
    google_client_id: str
    google_client_secret: str
    session_secret: str
    domain: str = "localhost"
    env: str = "development"

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


settings = Settings()
