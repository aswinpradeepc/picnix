from config.settings import Settings
from observability import bootstrap
import importlib


def make_settings(**overrides) -> Settings:
    values = {
        "google_maps_api_key": "gmaps-key",
        "mapbox_token": "mapbox-token",
        "google_cloud_project": "picnix-project",
        "google_cloud_location": "global",
        "google_application_credentials": "",
    }
    values.update(overrides)
    return Settings(**values)


def test_observability_disabled_by_default_noops() -> None:
    bootstrap._CONFIGURED = False

    configured = bootstrap.configure_observability(
        make_settings(observability_enabled=False)
    )

    assert configured is False
    assert bootstrap._CONFIGURED is False


def test_non_phoenix_product_noops() -> None:
    bootstrap._CONFIGURED = False

    configured = bootstrap.configure_observability(
        make_settings(observability_enabled=True, arize_product="ax")
    )

    assert configured is False
    assert bootstrap._CONFIGURED is False


def test_content_trace_config_hides_content_by_default() -> None:
    config = bootstrap._content_trace_config(capture_content=False)

    assert config.hide_inputs is True
    assert config.hide_outputs is True
    assert config.hide_input_messages is True
    assert config.hide_output_messages is True
    assert config.hide_prompts is True
    assert config.hide_choices is True


def test_phoenix_setup_registers_and_instruments_langchain(monkeypatch) -> None:
    from openinference.instrumentation import langchain as oi_langchain

    monkeypatch.setenv("PHOENIX_WORKING_DIR", "/tmp/picnix-phoenix-test")
    phoenix_otel = importlib.import_module("phoenix.otel")

    calls: dict[str, object] = {}

    def fake_register(**kwargs):
        calls["register"] = kwargs
        return "tracer-provider"

    class FakeInstrumentor:
        def instrument(self, **kwargs) -> None:
            calls["instrument"] = kwargs

    monkeypatch.setattr(phoenix_otel, "register", fake_register)
    monkeypatch.setattr(oi_langchain, "LangChainInstrumentor", FakeInstrumentor)

    bootstrap._CONFIGURED = False
    configured = bootstrap.configure_observability(
        make_settings(
            observability_enabled=True,
            arize_product="phoenix",
            arize_project_name="picnix-test",
            phoenix_api_key="phoenix-key",
            phoenix_collector_endpoint="http://localhost:6006",
        )
    )

    assert configured is True
    assert bootstrap._CONFIGURED is True
    assert calls["register"] == {
        "project_name": "picnix-test",
        "auto_instrument": False,
        "batch": True,
        "endpoint": "http://localhost:6006",
        "api_key": "phoenix-key",
    }
    assert calls["instrument"]["tracer_provider"] == "tracer-provider"
    assert calls["instrument"]["config"].hide_inputs is True

    bootstrap._CONFIGURED = False
