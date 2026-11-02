import logging
from django.conf import settings
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

TOKEN_SALT = "accounts.email_verification"
TOKEN_MAX_AGE = 3 * 86400  # 3 days in seconds


def generate_verification_token(user):
    signer = TimestampSigner(salt=TOKEN_SALT)
    return signer.sign(f"{user.pk}:{user.email}")


def verify_token(token):
    signer = TimestampSigner(salt=TOKEN_SALT)
    try:
        data = signer.unsign(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    try:
        pk_str, email = data.split(":", 1)
        return int(pk_str), email
    except (ValueError, TypeError):
        return None


def send_verification_email(user, request=None):
    """
    Constructs and sends an email verification link to the given user.
    Uses HTML and plain text templates.
    Logs errors if sending fails instead of silently swallowing them.
    In DEBUG mode, outputs the verification URL to standard output/logs.
    Returns (success: bool, verify_url: str).
    """
    token = generate_verification_token(user)
    if request:
        verify_url = request.build_absolute_uri(reverse("accounts:verify", args=[token]))
    else:
        site_domain = getattr(settings, "SITE_DOMAIN", "localhost:8000")
        scheme = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
        verify_url = f"{scheme}://{site_domain}{reverse('accounts:verify', args=[token])}"

    site_name = getattr(settings, "SITE_NAME", "Gayn Kotor")
    user_display = user.get_full_name() or user.username or "Student"
    subject = f"Verify your email - {site_name}"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost")

    context = {
        "user": user,
        "user_display_name": user_display,
        "site_name": site_name,
        "verify_url": verify_url,
        "year": timezone.now().year,
    }

    try:
        plain_message = render_to_string("accounts/email/verification_email.txt", context)
    except Exception:
        plain_message = (
            f"Hi {user_display},\n\n"
            f"Welcome to {site_name}! Please verify your email:\n{verify_url}\n\n"
            f"This link expires in 3 days."
        )

    try:
        html_message = render_to_string("accounts/email/verification_email.html", context)
    except Exception:
        html_message = None

    if getattr(settings, "DEBUG", False):
        print(
            f"\n"
            f"======================================================================\n"
            f"[EMAIL VERIFICATION DISPATCHED]\n"
            f"Recipient: {user.email}\n"
            f"Verify URL: {verify_url}\n"
            f"======================================================================\n"
        )

    try:
        sent_count = send_mail(
            subject=subject,
            message=plain_message,
            from_email=from_email,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("Verification email sent to %s (count=%s)", user.email, sent_count)
        return True, verify_url
    except Exception as exc:
        logger.error(
            "Failed to send email verification to %s: %s",
            user.email,
            exc,
            exc_info=True,
        )
        return False, verify_url
