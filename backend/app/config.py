# config.py — env-based settings. Mirrors the firmware's config.h principle:
# nothing hardcoded elsewhere, one place to look.
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://minesight:minesight@localhost:5432/minesight"
    default_org_name: str = "Default Org"


settings = Settings()
