import logging
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

try:
    from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
except ImportError:  # pragma: no cover - defensive for package API changes.
    ChatGoogleGenerativeAIError = None  # type: ignore[assignment]
from tenacity import (
    Retrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from config.settings import SETTINGS, Settings


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
REASONING_GEMINI_MODEL = "gemini-3.1-pro-preview"

LOGGER = logging.getLogger(__name__)

try:
    from google.api_core import exceptions as google_exceptions
except ImportError:  # pragma: no cover - google dependencies are provided by langchain-google-genai.
    google_exceptions = None

GOOGLE_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = ()
if google_exceptions is not None:
    GOOGLE_RETRYABLE_ERRORS = tuple(
        error_type
        for error_type in (
            getattr(google_exceptions, "ResourceExhausted", None),
            getattr(google_exceptions, "TooManyRequests", None),
        )
        if error_type is not None
    )

RETRYABLE_GEMINI_ERROR_NAMES = {
    "ChatGoogleGenerativeAIError",
    "ResourceExhausted",
    "TooManyRequests",
}
RETRYABLE_GEMINI_ERROR_MARKERS = (
    "429",
    "RESOURCE_EXHAUSTED",
    "TOO_MANY_REQUESTS",
    "RATE_LIMIT",
    "RATE LIMIT",
    "QUOTA",
)


class VertexConfigurationError(RuntimeError):
    pass


def _stringify_exception_attr(exc: BaseException, attr: str) -> str:
    value = getattr(exc, attr, "")
    if callable(value):
        try:
            value = value()
        except TypeError:
            value = ""
    return str(value)


def _has_retryable_gemini_marker(exc: BaseException) -> bool:
    details = " ".join(
        value
        for value in (
            type(exc).__name__,
            str(exc),
            _stringify_exception_attr(exc, "code"),
            _stringify_exception_attr(exc, "status"),
            _stringify_exception_attr(exc, "reason"),
        )
        if value
    ).upper()
    return any(marker in details for marker in RETRYABLE_GEMINI_ERROR_MARKERS)


def is_retryable_gemini_error(exc: BaseException) -> bool:
    if GOOGLE_RETRYABLE_ERRORS and isinstance(exc, GOOGLE_RETRYABLE_ERRORS):
        return True
    if ChatGoogleGenerativeAIError is not None and isinstance(exc, ChatGoogleGenerativeAIError):
        return _has_retryable_gemini_marker(exc)
    if type(exc).__name__ in RETRYABLE_GEMINI_ERROR_NAMES:
        return _has_retryable_gemini_marker(exc)
    return False


class RetryingChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
    llm_retry_attempts: int = 5
    llm_retry_backoff_min_seconds: float = 1.0
    llm_retry_backoff_max_seconds: float = 30.0

    def _retryer(self) -> Retrying:
        attempts = max(1, int(self.llm_retry_attempts))
        min_wait = max(0.0, float(self.llm_retry_backoff_min_seconds))
        max_wait = max(min_wait, float(self.llm_retry_backoff_max_seconds))
        multiplier = min_wait if min_wait > 0 else 1
        return Retrying(
            retry=retry_if_exception(is_retryable_gemini_error),
            wait=wait_random_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
            stop=stop_after_attempt(attempts),
            before_sleep=self._log_retry_sleep,
            reraise=True,
        )

    def _log_retry_sleep(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        sleep = retry_state.next_action.sleep if retry_state.next_action else 0
        LOGGER.warning(
            "Gemini model %s hit retryable %s; retrying in %.2fs after attempt %s.",
            self.model,
            type(exc).__name__ if exc else "error",
            sleep,
            retry_state.attempt_number,
        )

    def invoke(self, input: Any, config: Any | None = None, **kwargs: Any) -> Any:
        parent_invoke = super().invoke
        return self._retryer()(parent_invoke, input, config, **kwargs)


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

    return RetryingChatGoogleGenerativeAI(
        model=model,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        vertexai=True,
        temperature=temperature,
        llm_retry_attempts=settings.llm_retry_attempts,
        llm_retry_backoff_min_seconds=settings.llm_retry_backoff_min_seconds,
        llm_retry_backoff_max_seconds=settings.llm_retry_backoff_max_seconds,
        **model_options,
    )
