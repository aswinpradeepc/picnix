from uuid import UUID

import pytest

from config.settings import Settings


def make_settings(
    *,
    resend_api_key: str = "resend-key",
    resend_from_email: str = "Picnix <verify@example.com>",
    app_base_url: str = "http://picnix.example:8501",
) -> Settings:
    return Settings(
        google_maps_api_key="gmaps-key",
        mapbox_token="mapbox-token",
        google_cloud_project="picnix-project",
        google_cloud_location="global",
        google_application_credentials="",
        resend_api_key=resend_api_key,
        resend_from_email=resend_from_email,
        app_base_url=app_base_url,
    )


def test_verification_link_adds_token_query_param() -> None:
    from email_utils import verification_link

    token = UUID("11111111-1111-1111-1111-111111111111")

    assert verification_link(token, settings=make_settings()) == (
        "http://picnix.example:8501/?verify=11111111-1111-1111-1111-111111111111"
    )


def test_send_verification_email_uses_resend_sdk(monkeypatch) -> None:
    import email_utils

    token = UUID("11111111-1111-1111-1111-111111111111")
    sent: dict = {}

    def fake_send(params):
        sent.update(params)
        return {"id": "email-1"}

    monkeypatch.setattr(email_utils.resend.Emails, "send", fake_send)

    result = email_utils.send_verification_email(
        to_email="alice@example.com",
        username="alice",
        verification_token=token,
        settings=make_settings(),
    )

    assert result == {"id": "email-1"}
    assert email_utils.resend.api_key == "resend-key"
    assert sent["from"] == "Picnix <verify@example.com>"
    assert sent["to"] == ["alice@example.com"]
    assert sent["subject"] == "Verify your Picnix account"
    assert "http://picnix.example:8501/?verify=11111111-1111-1111-1111-111111111111" in sent["html"]
    assert "http://picnix.example:8501/?verify=11111111-1111-1111-1111-111111111111" in sent["text"]


def test_send_verification_email_requires_api_key() -> None:
    from email_utils import EmailDeliveryError, send_verification_email

    with pytest.raises(EmailDeliveryError, match="RESEND_API_KEY"):
        send_verification_email(
            to_email="alice@example.com",
            username="alice",
            verification_token=UUID("11111111-1111-1111-1111-111111111111"),
            settings=make_settings(resend_api_key=""),
        )
