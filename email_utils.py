from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import resend

from config.settings import SETTINGS, Settings


class EmailDeliveryError(RuntimeError):
    pass


def verification_link(token: UUID, *, settings: Settings = SETTINGS) -> str:
    base_url = settings.app_base_url.rstrip("/") or "http://localhost:8501"
    return f"{base_url}/?{urlencode({'verify': str(token)})}"


def send_verification_email(
    *,
    to_email: str,
    username: str,
    verification_token: UUID,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    if not settings.resend_api_key:
        raise EmailDeliveryError("RESEND_API_KEY is required to send verification email.")

    link = verification_link(verification_token, settings=settings)
    safe_username = escape(username)
    safe_link = escape(link, quote=True)

    resend.api_key = settings.resend_api_key
    try:
        return resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": "Verify your Picnix account",
                "html": (
                    f"<p>Hi {safe_username},</p>"
                    "<p>Verify your Picnix account to start planning trips.</p>"
                    f'<p><a href="{safe_link}">Verify your email</a></p>'
                    f"<p>If the button does not work, open this link: {safe_link}</p>"
                ),
                "text": (
                    f"Hi {username},\n\n"
                    "Verify your Picnix account to start planning trips:\n"
                    f"{link}\n"
                ),
            }
        )
    except Exception as exc:
        raise EmailDeliveryError("Failed to send verification email.") from exc
