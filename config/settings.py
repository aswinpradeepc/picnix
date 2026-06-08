from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


GOOGLE_MAPS_API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
MAPBOX_TOKEN_ENV = "MAPBOX_TOKEN"
GOOGLE_CLOUD_PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
GOOGLE_CLOUD_LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"
GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
DEBUG_ENV = "DEBUG"

REQUIRED_ENV_KEYS = (
    GOOGLE_MAPS_API_KEY_ENV,
    MAPBOX_TOKEN_ENV,
    GOOGLE_CLOUD_PROJECT_ENV,
    GOOGLE_CLOUD_LOCATION_ENV,
)


@dataclass(frozen=True)
class Settings:
    google_maps_api_key: str
    mapbox_token: str
    google_cloud_project: str
    google_cloud_location: str
    google_application_credentials: str
    debug: bool = False

    @property
    def vertex_auth_mode(self) -> str:
        return "service_account" if self.google_application_credentials else "adc"


def _env_value(key: str) -> str:
    return os.getenv(key, "").strip()


def load_settings(env_file: str | Path = ".env", *, override: bool = False) -> Settings:
    """Load Picnix settings from a dotenv file and the process environment."""
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=override)

    return Settings(
        google_maps_api_key=_env_value(GOOGLE_MAPS_API_KEY_ENV),
        mapbox_token=_env_value(MAPBOX_TOKEN_ENV),
        google_cloud_project=_env_value(GOOGLE_CLOUD_PROJECT_ENV),
        google_cloud_location=_env_value(GOOGLE_CLOUD_LOCATION_ENV),
        google_application_credentials=_env_value(GOOGLE_APPLICATION_CREDENTIALS_ENV),
        debug=_env_value(DEBUG_ENV).lower() in ("1", "true", "yes"),
    )


def missing_required_keys(settings: Settings) -> list[str]:
    field_by_env_key = {
        GOOGLE_MAPS_API_KEY_ENV: "google_maps_api_key",
        MAPBOX_TOKEN_ENV: "mapbox_token",
        GOOGLE_CLOUD_PROJECT_ENV: "google_cloud_project",
        GOOGLE_CLOUD_LOCATION_ENV: "google_cloud_location",
    }

    return [
        key
        for key, field_name in field_by_env_key.items()
        if not getattr(settings, field_name)
    ]


SETTINGS = load_settings()
GOOGLE_MAPS_API_KEY = SETTINGS.google_maps_api_key
MAPBOX_TOKEN = SETTINGS.mapbox_token
GOOGLE_CLOUD_PROJECT = SETTINGS.google_cloud_project
GOOGLE_CLOUD_LOCATION = SETTINGS.google_cloud_location
GOOGLE_APPLICATION_CREDENTIALS = SETTINGS.google_application_credentials
VERTEX_AUTH_MODE = SETTINGS.vertex_auth_mode
DEBUG = SETTINGS.debug
