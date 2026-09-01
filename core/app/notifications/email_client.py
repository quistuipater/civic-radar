"""Thin SMTP client for emailing narrative summaries. Same degrade-on-
failure contract as the AI clients: never raises, returns an error string
instead -- a mail-server outage or misconfigured credentials must not take
down the worker tick, only leave that issue un-emailed (it's still filed
in the dashboard either way; see app/summaries/models via NarrativeSummary
.email_error).
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.summary_recipient_email)


def send_summary_email(subject: str, markdown_body: str, html_body: str) -> str | None:
    """Returns None on success, an error message on failure. No-ops (with an
    error message, not a crash) if SMTP isn't configured -- see is_configured().
    """
    if not is_configured():
        return "SMTP not configured (smtp_host/smtp_username/smtp_password/summary_recipient_email)"

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.smtp_username
    message["To"] = settings.summary_recipient_email
    message.attach(MIMEText(markdown_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_username, [settings.summary_recipient_email], message.as_string())
        return None
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("failed to send summary email %r: %s", subject, exc)
        return f"smtp send failed: {exc}"
