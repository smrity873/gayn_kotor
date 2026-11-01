from django.conf import settings
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.urls import reverse

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
    token = generate_verification_token(user)
    if request:
        verify_url = request.build_absolute_uri(reverse("accounts:verify", args=[token]))
    else:
        verify_url = f"/accounts/verify/{token}/"

    site_name = getattr(settings, "SITE_NAME", "Gayn Kotor")
    subject = f"Verify your email - {site_name}"
    message = (
        f"Hi {user.first_name or user.username},\n\n"
        f"Thank you for signing up on {site_name}.\n"
        f"Please verify your email address by clicking the link below:\n\n"
        f"{verify_url}\n\n"
        f"This link will expire in 3 days.\n\n"
        f"If you did not sign up for {site_name}, please ignore this email.\n"
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost")
    send_mail(subject, message, from_email, [user.email], fail_silently=True)
