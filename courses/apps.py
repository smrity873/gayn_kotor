from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "courses"

    def ready(self):
        from payments.models import PaymentOrder
        from payments.registry import register_fulfiller
        from .services import fulfill_course_purchase

        register_fulfiller(PaymentOrder.Purpose.COURSE, fulfill_course_purchase)
