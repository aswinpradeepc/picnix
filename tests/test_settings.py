import importlib
import importlib.util
from pathlib import Path


REQUIRED_ENV_KEYS = [
    "GOOGLE_MAPS_API_KEY",
    "MAPBOX_TOKEN",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
]


OPTIONAL_ENV_KEYS = [
    "GOOGLE_APPLICATION_CREDENTIALS",
    "DEBUG",
    "OBSERVABILITY_ENABLED",
    "ARIZE_PRODUCT",
    "ARIZE_PROJECT_NAME",
    "OBSERVABILITY_CAPTURE_CONTENT",
    "PHOENIX_API_KEY",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "PHOENIX_ENABLE_AUTH",
    "PHOENIX_SECRET",
    "PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD",
    "PHOENIX_ENABLE_STRONG_PASSWORD_POLICY",
    "PHOENIX_CSRF_TRUSTED_ORIGINS",
]

ENV_EXAMPLE_EXPECTED_LINES = {
    "GOOGLE_MAPS_API_KEY": "GOOGLE_MAPS_API_KEY=",
    "MAPBOX_TOKEN": "MAPBOX_TOKEN=",
    "GOOGLE_CLOUD_PROJECT": "GOOGLE_CLOUD_PROJECT=",
    "GOOGLE_CLOUD_LOCATION": "GOOGLE_CLOUD_LOCATION=",
    "GOOGLE_APPLICATION_CREDENTIALS": "GOOGLE_APPLICATION_CREDENTIALS=",
    "DEBUG": "DEBUG=false",
    "OBSERVABILITY_ENABLED": "OBSERVABILITY_ENABLED=false",
    "ARIZE_PRODUCT": "ARIZE_PRODUCT=phoenix",
    "ARIZE_PROJECT_NAME": "ARIZE_PROJECT_NAME=picnix-local",
    "OBSERVABILITY_CAPTURE_CONTENT": "OBSERVABILITY_CAPTURE_CONTENT=false",
    "PHOENIX_API_KEY": "PHOENIX_API_KEY=",
    "PHOENIX_COLLECTOR_ENDPOINT": "PHOENIX_COLLECTOR_ENDPOINT=",
    "PHOENIX_ENABLE_AUTH": "PHOENIX_ENABLE_AUTH=false",
    "PHOENIX_SECRET": "PHOENIX_SECRET=",
    "PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD": "PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD=",
    "PHOENIX_ENABLE_STRONG_PASSWORD_POLICY": "PHOENIX_ENABLE_STRONG_PASSWORD_POLICY=true",
    "PHOENIX_CSRF_TRUSTED_ORIGINS": "PHOENIX_CSRF_TRUSTED_ORIGINS=",
}


def test_settings_module_exists() -> None:
    assert importlib.util.find_spec("config.settings") is not None


def test_env_example_lists_expected_keys_and_defaults() -> None:
    env_example = Path(".env.example")

    assert env_example.exists()

    lines_by_key = {
        line.split("=", 1)[0]: line
        for line in env_example.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    expected_keys = list(ENV_EXAMPLE_EXPECTED_LINES)

    assert list(lines_by_key) == expected_keys
    assert lines_by_key == ENV_EXAMPLE_EXPECTED_LINES


def test_load_settings_reads_dotenv_file(tmp_path: Path, monkeypatch) -> None:
    for key in REQUIRED_ENV_KEYS + OPTIONAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GOOGLE_MAPS_API_KEY=gmaps-key",
                "MAPBOX_TOKEN=mapbox-token",
                "GOOGLE_CLOUD_PROJECT=picnix-gcp",
                "GOOGLE_CLOUD_LOCATION=asia-south1",
                "GOOGLE_APPLICATION_CREDENTIALS=",
                "DEBUG=true",
                "OBSERVABILITY_ENABLED=true",
                "ARIZE_PRODUCT=phoenix",
                "ARIZE_PROJECT_NAME=picnix-test",
                "OBSERVABILITY_CAPTURE_CONTENT=true",
                "PHOENIX_API_KEY=phoenix-key",
                "PHOENIX_COLLECTOR_ENDPOINT=http://phoenix.example:6006",
            ]
        ),
        encoding="utf-8",
    )

    settings_module = importlib.import_module("config.settings")
    settings = settings_module.load_settings(env_file, override=True)

    assert settings.google_maps_api_key == "gmaps-key"
    assert settings.mapbox_token == "mapbox-token"
    assert settings.google_cloud_project == "picnix-gcp"
    assert settings.google_cloud_location == "asia-south1"
    assert settings.google_application_credentials == ""
    assert settings.vertex_auth_mode == "adc"
    assert settings.debug is True
    assert settings.observability_enabled is True
    assert settings.arize_product == "phoenix"
    assert settings.arize_project_name == "picnix-test"
    assert settings.observability_capture_content is True
    assert settings.phoenix_api_key == "phoenix-key"
    assert settings.phoenix_collector_endpoint == "http://phoenix.example:6006"
    assert settings_module.missing_required_keys(settings) == []


def test_missing_required_keys_reports_blank_values(tmp_path: Path, monkeypatch) -> None:
    for key in REQUIRED_ENV_KEYS + OPTIONAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GOOGLE_MAPS_API_KEY=",
                "MAPBOX_TOKEN=mapbox-token",
                "GOOGLE_CLOUD_PROJECT=",
                "GOOGLE_CLOUD_LOCATION=",
                "GOOGLE_APPLICATION_CREDENTIALS=/tmp/picnix-service-account.json",
            ]
        ),
        encoding="utf-8",
    )

    settings_module = importlib.import_module("config.settings")
    settings = settings_module.load_settings(env_file, override=True)

    assert settings_module.missing_required_keys(settings) == [
        "GOOGLE_MAPS_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ]


def test_service_account_path_switches_vertex_auth_mode(tmp_path: Path, monkeypatch) -> None:
    for key in REQUIRED_ENV_KEYS + OPTIONAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GOOGLE_MAPS_API_KEY=gmaps-key",
                "MAPBOX_TOKEN=mapbox-token",
                "GOOGLE_CLOUD_PROJECT=picnix-gcp",
                "GOOGLE_CLOUD_LOCATION=asia-south1",
                "GOOGLE_APPLICATION_CREDENTIALS=/tmp/picnix-service-account.json",
            ]
        ),
        encoding="utf-8",
    )

    settings_module = importlib.import_module("config.settings")
    settings = settings_module.load_settings(env_file, override=True)

    assert settings.vertex_auth_mode == "service_account"
