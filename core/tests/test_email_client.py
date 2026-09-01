"""Tests for app.notifications.email_client -- smtplib.SMTP_SSL is mocked
so these run without a real mail server, matching the mocking pattern used
for the other external clients (ollama_client, claude_client).
"""

import app.notifications.email_client as email_client_module
from app.notifications.email_client import is_configured, send_summary_email


def _configure(monkeypatch, **overrides):
    values = dict(
        smtp_host="mail.example.com",
        smtp_port=465,
        smtp_username="admin@example.com",
        smtp_password="secret",
        summary_recipient_email="me@example.com",
    )
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(email_client_module.settings, key, value)


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.logged_in = None
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, username, password):
        self.logged_in = (username, password)

    def sendmail(self, from_addr, to_addrs, message):
        self.sent = (from_addr, to_addrs, message)


class TestIsConfigured:
    def test_false_when_nothing_set(self, monkeypatch):
        _configure(monkeypatch, smtp_host=None, smtp_username=None, smtp_password=None, summary_recipient_email=None)
        assert is_configured() is False

    def test_false_when_partially_set(self, monkeypatch):
        _configure(monkeypatch, summary_recipient_email=None)
        assert is_configured() is False

    def test_true_when_fully_configured(self, monkeypatch):
        _configure(monkeypatch)
        assert is_configured() is True


class TestSendSummaryEmail:
    def test_returns_error_when_not_configured(self, monkeypatch):
        _configure(monkeypatch, smtp_host=None)
        error = send_summary_email("subject", "body", "<p>body</p>")
        assert "SMTP not configured" in error

    def test_sends_successfully_and_returns_none(self, monkeypatch):
        _configure(monkeypatch)
        FakeSMTP.instances = []
        monkeypatch.setattr(email_client_module.smtplib, "SMTP_SSL", FakeSMTP)

        error = send_summary_email("Subject line", "plain body", "<p>html body</p>")

        assert error is None
        assert len(FakeSMTP.instances) == 1
        instance = FakeSMTP.instances[0]
        assert instance.logged_in == ("admin@example.com", "secret")
        assert instance.sent[0] == "admin@example.com"
        assert instance.sent[1] == ["me@example.com"]
        assert "Subject line" in instance.sent[2]

    def test_returns_error_message_on_smtp_failure(self, monkeypatch):
        _configure(monkeypatch)

        class FailingSMTP(FakeSMTP):
            def login(self, username, password):
                raise OSError("connection refused")

        monkeypatch.setattr(email_client_module.smtplib, "SMTP_SSL", FailingSMTP)

        error = send_summary_email("subject", "body", "<p>body</p>")

        assert "smtp send failed" in error
