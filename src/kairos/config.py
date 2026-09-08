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
    redirect_uri: str = "http://localhost:8000/auth/callback"
    env: str = "development"
    # delay between backfill windows, deliberately configurable (not hardcoded)
    # so it can be tuned per-environment without a code change; keep this
    # conservative -- Garmin's SSO endpoint Cloudflare-banned this project's
    # dev IP for a few hours after a burst of login attempts during testing,
    # so avoid discovering the data-endpoint limit the same way.
    garmin_backfill_throttle_seconds: float = 1.5

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


settings = Settings()  # type: ignore[call-arg]
