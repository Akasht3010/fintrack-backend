from unittest.mock import patch

import pytest

from app.services import email_service


def test_prints_otp_to_console_when_env_is_development_and_smtp_unconfigured(capsys):
    with patch.object(email_service, "SMTP_HOST", None), \
         patch.object(email_service, "ENV", "development"):
        email_service.send_otp_email("someone@example.com", "Someone", "123456")
    assert "123456" in capsys.readouterr().out


def test_raises_instead_of_printing_when_env_is_not_development():
    """A misconfigured/partially-rolled-out production deploy (SMTP unset)
    must fail loudly, not silently write a live 2FA code to logs."""
    with patch.object(email_service, "SMTP_HOST", None), \
         patch.object(email_service, "ENV", "production"):
        with pytest.raises(RuntimeError):
            email_service.send_otp_email("someone@example.com", "Someone", "123456")
