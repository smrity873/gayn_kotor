from django.conf import settings


def site_name(request):
    return {
        "SITE_NAME": getattr(settings, "SITE_NAME", "Gayn Kotor"),
    }
