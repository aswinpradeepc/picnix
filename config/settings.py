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
OBSERVABILITY_ENABLED_ENV = "OBSERVABILITY_ENABLED"
ARIZE_PRODUCT_ENV = "ARIZE_PRODUCT"
ARIZE_PROJECT_NAME_ENV = "ARIZE_PROJECT_NAME"
OBSERVABILITY_CAPTURE_CONTENT_ENV = "OBSERVABILITY_CAPTURE_CONTENT"
PHOENIX_API_KEY_ENV = "PHOENIX_API_KEY"
PHOENIX_COLLECTOR_ENDPOINT_ENV = "PHOENIX_COLLECTOR_ENDPOINT"
DATABASE_URL_ENV = "DATABASE_URL"
AUTH_COOKIE_NAME_ENV = "AUTH_COOKIE_NAME"
AUTH_COOKIE_KEY_ENV = "AUTH_COOKIE_KEY"
AUTH_COOKIE_EXPIRY_DAYS_ENV = "AUTH_COOKIE_EXPIRY_DAYS"

LOCAL_DATABASE_URL = "postgresql://picnix:picnix@localhost:5432/picnix"
LOCAL_AUTH_COOKIE_KEY = "picnix-local-auth-cookie-key"

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
    observability_enabled: bool = False
    arize_product: str = "phoenix"
    arize_project_name: str = "picnix-local"
    observability_capture_content: bool = False
    phoenix_api_key: str = ""
    phoenix_collector_endpoint: str = ""
    database_url: str = LOCAL_DATABASE_URL
    auth_cookie_name: str = "picnix_auth"
    auth_cookie_key: str = LOCAL_AUTH_COOKIE_KEY
    auth_cookie_expiry_days: float = 30.0

    @property
    def vertex_auth_mode(self) -> str:
        return "service_account" if self.google_application_credentials else "adc"


def _env_value(key: str) -> str:
    return os.getenv(key, "").strip()


def _env_bool(key: str) -> bool:
    return _env_value(key).lower() in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    value = _env_value(key)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


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
        debug=_env_bool(DEBUG_ENV),
        observability_enabled=_env_bool(OBSERVABILITY_ENABLED_ENV),
        arize_product=(_env_value(ARIZE_PRODUCT_ENV) or "phoenix").lower(),
        arize_project_name=_env_value(ARIZE_PROJECT_NAME_ENV) or "picnix-local",
        observability_capture_content=_env_bool(OBSERVABILITY_CAPTURE_CONTENT_ENV),
        phoenix_api_key=_env_value(PHOENIX_API_KEY_ENV),
        phoenix_collector_endpoint=_env_value(PHOENIX_COLLECTOR_ENDPOINT_ENV),
        database_url=_env_value(DATABASE_URL_ENV) or LOCAL_DATABASE_URL,
        auth_cookie_name=_env_value(AUTH_COOKIE_NAME_ENV) or "picnix_auth",
        auth_cookie_key=_env_value(AUTH_COOKIE_KEY_ENV) or LOCAL_AUTH_COOKIE_KEY,
        auth_cookie_expiry_days=_env_float(AUTH_COOKIE_EXPIRY_DAYS_ENV, 30.0),
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
OBSERVABILITY_ENABLED = SETTINGS.observability_enabled
ARIZE_PRODUCT = SETTINGS.arize_product
ARIZE_PROJECT_NAME = SETTINGS.arize_project_name
OBSERVABILITY_CAPTURE_CONTENT = SETTINGS.observability_capture_content
PHOENIX_API_KEY = SETTINGS.phoenix_api_key
PHOENIX_COLLECTOR_ENDPOINT = SETTINGS.phoenix_collector_endpoint
DATABASE_URL = SETTINGS.database_url
AUTH_COOKIE_NAME = SETTINGS.auth_cookie_name
AUTH_COOKIE_KEY = SETTINGS.auth_cookie_key
AUTH_COOKIE_EXPIRY_DAYS = SETTINGS.auth_cookie_expiry_days
