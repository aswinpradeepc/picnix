from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from config.settings import SETTINGS, Settings


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class VertexConfigurationError(RuntimeError):
    pass


def get_chat_model(
    *,
    settings: Settings = SETTINGS,
    model: str = DEFAULT_GEMINI_MODEL,
    temperature: float = 0.2,
    **model_options: Any,
) -> ChatGoogleGenerativeAI:
    if not settings.google_cloud_project:
        raise VertexConfigurationError("GOOGLE_CLOUD_PROJECT is required for Vertex AI.")
    if not settings.google_cloud_location:
        raise VertexConfigurationError("GOOGLE_CLOUD_LOCATION is required for Vertex AI.")

    return ChatGoogleGenerativeAI(
        model=model,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        vertexai=True,
        temperature=temperature,
        **model_options,
    )
