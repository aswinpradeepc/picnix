import importlib
import importlib.util
from pathlib import Path


REQUIRED_ENV_KEYS = [
    "GOOGLE_MAPS_API_KEY",
    "MAPBOX_TOKEN",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
]


def test_settings_module_exists() -> None:
    assert importlib.util.find_spec("config.settings") is not None


def test_env_example_lists_required_keys_without_values() -> None:
    env_example = Path(".env.example")

    assert env_example.exists()

    lines_by_key = {
        line.split("=", 1)[0]: line
        for line in env_example.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    assert list(lines_by_key) == REQUIRED_ENV_KEYS
    assert all(lines_by_key[key] == f"{key}=" for key in REQUIRED_ENV_KEYS)


def test_load_settings_reads_dotenv_file(tmp_path: Path, monkeypatch) -> None:
    for key in REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GOOGLE_MAPS_API_KEY=gmaps-key",
                "MAPBOX_TOKEN=mapbox-token",
                "GOOGLE_CLOUD_PROJECT=picnix-gcp",
                "GOOGLE_APPLICATION_CREDENTIALS=/tmp/picnix-service-account.json",
            ]
        ),
        encoding="utf-8",
    )

    settings_module = importlib.import_module("config.settings")
    settings = settings_module.load_settings(env_file, override=True)

    assert settings.google_maps_api_key == "gmaps-key"
    assert settings.mapbox_token == "mapbox-token"
    assert settings.google_cloud_project == "picnix-gcp"
    assert settings.google_application_credentials == "/tmp/picnix-service-account.json"
    assert settings_module.missing_required_keys(settings) == []


def test_missing_required_keys_reports_blank_values(tmp_path: Path, monkeypatch) -> None:
    for key in REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GOOGLE_MAPS_API_KEY=",
                "MAPBOX_TOKEN=mapbox-token",
                "GOOGLE_CLOUD_PROJECT=",
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
    ]
