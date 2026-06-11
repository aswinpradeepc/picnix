from __future__ import annotations

import os
from typing import Any

from config.settings import SETTINGS, Settings


_CONFIGURED = False


def _content_trace_config(capture_content: bool) -> Any:
    from openinference.instrumentation import TraceConfig

    if capture_content:
        return TraceConfig()
    return TraceConfig(
        hide_inputs=True,
        hide_outputs=True,
        hide_input_messages=True,
        hide_output_messages=True,
        hide_input_text=True,
        hide_output_text=True,
        hide_prompts=True,
        hide_choices=True,
    )


def configure_observability(settings: Settings = SETTINGS) -> bool:
    """Configure Phoenix/OpenInference tracing before LangGraph and LangChain are imported.

    This milestone intentionally keeps tracing broad and automatic: Phoenix is the only
    active backend, and the OpenInference LangChain instrumentor supplies LangGraph and
    LangChain spans. Manual node/tool spans are deferred.
    """
    global _CONFIGURED
    if _CONFIGURED or not settings.observability_enabled:
        return False

    if settings.arize_product != "phoenix":
        print(
            "Observability disabled: this milestone supports ARIZE_PRODUCT=phoenix only."
        )
        return False

    try:
        os.environ.setdefault("PHOENIX_WORKING_DIR", "/tmp/picnix-phoenix")

        from openinference.instrumentation.langchain import LangChainInstrumentor
        from phoenix.otel import register

        register_kwargs: dict[str, Any] = {
            "project_name": settings.arize_project_name,
            "auto_instrument": False,
            "batch": True,
        }
        if settings.phoenix_collector_endpoint:
            register_kwargs["endpoint"] = settings.phoenix_collector_endpoint
        if settings.phoenix_api_key:
            register_kwargs["api_key"] = settings.phoenix_api_key

        tracer_provider = register(**register_kwargs)
        LangChainInstrumentor().instrument(
            tracer_provider=tracer_provider,
            config=_content_trace_config(settings.observability_capture_content),
        )
    except Exception as exc:
        print(f"Observability disabled: Phoenix/OpenInference setup failed: {exc}")
        return False

    _CONFIGURED = True
    return True
