# config.py — env-based settings. Mirrors the firmware's config.h principle:
# nothing hardcoded elsewhere, one place to look.
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://minesight:minesight@localhost:5432/minesight"
    default_org_name: str = "Default Org"
    # Traccar management REST API, used to auto-create devices when a vehicle is
    # registered in our dashboard. All optional: unset means device creation is skipped
    # (traccar_status="skipped") — the backend runs fine without them.
    traccar_api_url: str | None = None  # e.g. http://traccar:8082/api
    traccar_api_user: str | None = None
    traccar_api_password: str | None = None


settings = Settings()
