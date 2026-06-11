from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


GOOGLE_MAPS_API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
MAPBOX_TOKEN_ENV = "MAPBOX_TOKEN"
GOOGLE_CLOUD_PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
GOOGLE_CLOUD_LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"
GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
LLM_RETRY_ATTEMPTS_ENV = "LLM_RETRY_ATTEMPTS"
LLM_RETRY_BACKOFF_MIN_SECONDS_ENV = "LLM_RETRY_BACKOFF_MIN_SECONDS"
LLM_RETRY_BACKOFF_MAX_SECONDS_ENV = "LLM_RETRY_BACKOFF_MAX_SECONDS"
RESEND_API_KEY_ENV = "RESEND_API_KEY"
RESEND_FROM_EMAIL_ENV = "RESEND_FROM_EMAIL"
APP_BASE_URL_ENV = "APP_BASE_URL"
DEBUG_ENV = "DEBUG"
OBSERVABILITY_ENABLED_ENV = "OBSERVABILITY_ENABLED"
ARIZE_PRODUCT_ENV = "ARIZE_PRODUCT"
ARIZE_PROJECT_NAME_ENV = "ARIZE_PROJECT_NAME"
OBSERVABILITY_CAPTURE_CONTENT_ENV = "OBSERVABILITY_CAPTURE_CONTENT"
PHOENIX_API_KEY_ENV = "PHOENIX_API_KEY"
PHOENIX_COLLECTOR_ENDPOINT_ENV = "PHOENIX_COLLECTOR_ENDPOINT"
PHOENIX_BASE_URL_ENV = "PHOENIX_BASE_URL"
DATABASE_URL_ENV = "DATABASE_URL"
AUTH_COOKIE_NAME_ENV = "AUTH_COOKIE_NAME"
AUTH_COOKIE_KEY_ENV = "AUTH_COOKIE_KEY"
AUTH_COOKIE_EXPIRY_DAYS_ENV = "AUTH_COOKIE_EXPIRY_DAYS"
ADMIN_USERNAMES_ENV = "ADMIN_USERNAMES"

LOCAL_DATABASE_URL = "postgresql://picnix:picnix@localhost:5432/picnix"
LOCAL_PHOENIX_BASE_URL = "http://localhost:6006"
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
    llm_retry_attempts: int = 5
    llm_retry_backoff_min_seconds: float = 1.0
    llm_retry_backoff_max_seconds: float = 30.0
    resend_api_key: str = ""
    resend_from_email: str = "Picnix <onboarding@resend.dev>"
    app_base_url: str = "http://localhost:8501"
    debug: bool = False
    observability_enabled: bool = False
    arize_product: str = "phoenix"
    arize_project_name: str = "picnix-local"
    observability_capture_content: bool = False
    phoenix_api_key: str = ""
    phoenix_collector_endpoint: str = ""
    phoenix_base_url: str = LOCAL_PHOENIX_BASE_URL
    database_url: str = LOCAL_DATABASE_URL
    auth_cookie_name: str = "picnix_auth"
    auth_cookie_key: str = LOCAL_AUTH_COOKIE_KEY
    auth_cookie_expiry_days: float = 30.0
    admin_usernames: tuple[str, ...] = ()

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


def _env_csv(key: str) -> tuple[str, ...]:
    return tuple(
        item.strip().lower()
        for item in _env_value(key).split(",")
        if item.strip()
    )


def _env_int(key: str, default: int) -> int:
    value = _env_value(key)
    if not value:
        return default
    try:
        return int(value)
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
        llm_retry_attempts=_env_int(LLM_RETRY_ATTEMPTS_ENV, 5),
        llm_retry_backoff_min_seconds=_env_float(LLM_RETRY_BACKOFF_MIN_SECONDS_ENV, 1.0),
        llm_retry_backoff_max_seconds=_env_float(LLM_RETRY_BACKOFF_MAX_SECONDS_ENV, 30.0),
        resend_api_key=_env_value(RESEND_API_KEY_ENV),
        resend_from_email=_env_value(RESEND_FROM_EMAIL_ENV)
        or "Picnix <onboarding@resend.dev>",
        app_base_url=_env_value(APP_BASE_URL_ENV) or "http://localhost:8501",
        debug=_env_bool(DEBUG_ENV),
        observability_enabled=_env_bool(OBSERVABILITY_ENABLED_ENV),
        arize_product=(_env_value(ARIZE_PRODUCT_ENV) or "phoenix").lower(),
        arize_project_name=_env_value(ARIZE_PROJECT_NAME_ENV) or "picnix-local",
        observability_capture_content=_env_bool(OBSERVABILITY_CAPTURE_CONTENT_ENV),
        phoenix_api_key=_env_value(PHOENIX_API_KEY_ENV),
        phoenix_collector_endpoint=_env_value(PHOENIX_COLLECTOR_ENDPOINT_ENV),
        phoenix_base_url=_env_value(PHOENIX_BASE_URL_ENV) or LOCAL_PHOENIX_BASE_URL,
        database_url=_env_value(DATABASE_URL_ENV) or LOCAL_DATABASE_URL,
        auth_cookie_name=_env_value(AUTH_COOKIE_NAME_ENV) or "picnix_auth",
        auth_cookie_key=_env_value(AUTH_COOKIE_KEY_ENV) or LOCAL_AUTH_COOKIE_KEY,
        auth_cookie_expiry_days=_env_float(AUTH_COOKIE_EXPIRY_DAYS_ENV, 30.0),
        admin_usernames=_env_csv(ADMIN_USERNAMES_ENV),
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
LLM_RETRY_ATTEMPTS = SETTINGS.llm_retry_attempts
LLM_RETRY_BACKOFF_MIN_SECONDS = SETTINGS.llm_retry_backoff_min_seconds
LLM_RETRY_BACKOFF_MAX_SECONDS = SETTINGS.llm_retry_backoff_max_seconds
RESEND_API_KEY = SETTINGS.resend_api_key
RESEND_FROM_EMAIL = SETTINGS.resend_from_email
APP_BASE_URL = SETTINGS.app_base_url
VERTEX_AUTH_MODE = SETTINGS.vertex_auth_mode
DEBUG = SETTINGS.debug
OBSERVABILITY_ENABLED = SETTINGS.observability_enabled
ARIZE_PRODUCT = SETTINGS.arize_product
ARIZE_PROJECT_NAME = SETTINGS.arize_project_name
OBSERVABILITY_CAPTURE_CONTENT = SETTINGS.observability_capture_content
PHOENIX_API_KEY = SETTINGS.phoenix_api_key
PHOENIX_COLLECTOR_ENDPOINT = SETTINGS.phoenix_collector_endpoint
PHOENIX_BASE_URL = SETTINGS.phoenix_base_url
DATABASE_URL = SETTINGS.database_url
AUTH_COOKIE_NAME = SETTINGS.auth_cookie_name
AUTH_COOKIE_KEY = SETTINGS.auth_cookie_key
AUTH_COOKIE_EXPIRY_DAYS = SETTINGS.auth_cookie_expiry_days
ADMIN_USERNAMES = SETTINGS.admin_usernames
