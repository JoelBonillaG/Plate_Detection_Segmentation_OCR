from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


class Settings:
    app_name: str = "Monitoreo vehicular universitario"
    admin_user: str = "Administrador"

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_host_port: int

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_encryption: str

    def __init__(self) -> None:
        self.postgres_db = os.getenv("POSTGRES_DB", "monitoreo_vehicular")
        self.postgres_user = os.getenv("POSTGRES_USER", "monitoreo_user")
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", "")
        self.postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        self.postgres_host_port = _get_int("POSTGRES_HOST_PORT", 5433)

        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = _get_int("SMTP_PORT", 587)
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", self.smtp_user)
        self.smtp_encryption = os.getenv("SMTP_ENCRYPTION", "starttls").lower()

    @property
    def database_url(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        host = self.postgres_host
        port = self.postgres_host_port
        db = quote_plus(self.postgres_db)
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
