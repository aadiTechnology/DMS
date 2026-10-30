"""Email delivery behind a small interface. Provider is a deployment choice (open decision D9):
`smtp` works with any provider; `console` is for local development only (it logs the message,
including links) and is rejected in production; `outbox` collects messages for tests.
Messages are English only for now; localized templates arrive with the localization sprint.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage

from app.core.config import Settings, get_settings

logger = logging.getLogger("dms.email")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


OUTBOX: list[EmailMessage] = []


def build_mime(settings: Settings, message: EmailMessage) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = settings.EMAIL_FROM
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime.set_content(message.body)
    return mime


def send(messages: list[EmailMessage]) -> None:
    """Deliver after the database transaction has committed. Failures are logged without the
    message body (it contains single-use links) and never raised into the request."""
    settings = get_settings()
    for message in messages:
        try:
            if settings.EMAIL_BACKEND == "outbox":
                OUTBOX.append(message)
            elif settings.EMAIL_BACKEND == "console":
                logger.warning(
                    "DEV EMAIL to=%s subject=%s\n%s", message.to, message.subject, message.body
                )
            else:
                with smtplib.SMTP(
                    settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT, timeout=15
                ) as smtp:
                    smtp.starttls()
                    if settings.EMAIL_SMTP_USER:
                        smtp.login(settings.EMAIL_SMTP_USER, settings.EMAIL_SMTP_PASSWORD)
                    smtp.send_message(build_mime(settings, message))
        except Exception:
            logger.exception("email delivery failed to=%s subject=%s", message.to, message.subject)


def invitation_email(settings: Settings, to: str, org_name: str, token: str) -> EmailMessage:
    link = f"{settings.APP_BASE_URL}/accept-invite?token={token}"
    return EmailMessage(
        to=to,
        subject=f"You are invited to {org_name} on DMS",
        body=(
            f"You have been invited to join {org_name}.\n\n"
            f"Open this link to set up your account (valid {settings.INVITE_TTL_HOURS // 24} days, single use):\n"
            f"{link}\n\nIf you did not expect this, ignore this email."
        ),
    )


def password_reset_email(settings: Settings, to: str, token: str) -> EmailMessage:
    link = f"{settings.APP_BASE_URL}/reset-password?token={token}"
    return EmailMessage(
        to=to,
        subject="Reset your DMS password",
        body=(
            f"Open this link to choose a new password (valid {settings.RESET_TTL_MINUTES} minutes, "
            f"single use):\n{link}\n\nIf you did not request this, ignore this email."
        ),
    )
