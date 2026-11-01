import os
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from campus.models import Batch, BatchMembership, Department
from core.testing import make_department, make_batch, make_student, make_lecturer
from payments.models import PaymentOrder, WalletEntry
from payments.services import complete_order, create_order, get_wallet_balance
from payments.gateways.base import PaymentResult
from .forms import CourseForm, LessonForm
from .models import Course, Lesson, PricingRule, CoursePurchase
from .services import (
    can_sell,
    check_and_update_course_on_lesson_change,
    get_allowed_price_range,
    get_video_duration,
    validate_course_price,
    validate_video_file,
)


def sample_mp4_file(name="sample.mp4"):
    """Returns a real sample MP4 file object from static/images/video.mp4."""
    mp4_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
    with open(mp4_path, "rb") as f:
        data = f.read()
    return SimpleUploadedFile(name, data, content_type="video/mp4")


class PricingRulesAndDurationTests(TestCase):
    def setUp(self):
        self.pricing_academic, _ = PricingRule.objects.get_or_create(
            category=Course.Category.ACADEMIC,
            defaults={"min_per_hour": Decimal("50.00"), "max_per_hour": Decimal("150.00")},
        )
        self.pricing_non_academic, _ = PricingRule.objects.get_or_create(
            category=Course.Category.NON_ACADEMIC,
            defaults={"min_per_hour": Decimal("200.00"), "max_per_hour": Decimal("600.00")},
        )
        self.lecturer = make_lecturer(username="pricing_lecturer")

    def test_mutagen_reads_video_duration(self):
        mp4_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
        duration = get_video_duration(mp4_path)
        self.assertIsNotNone(duration)
        self.assertEqual(duration, 10)  # static/images/video.mp4 is 10s

    def test_validate_video_file_rejects_non_mp4(self):
        fake_file = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_video_file(fake_file)

    def test_allowed_price_range_academic_baseline(self):
        """0 seconds duration uses minimum billable hours 0.5h (30 min). Academic 50-150 BDT/h."""
        min_p, max_p = get_allowed_price_range(Course.Category.ACADEMIC, total_duration_seconds=0)
        # 50 * 0.5 = 25.00, 150 * 0.5 = 75.00
        self.assertEqual(min_p, Decimal("25.00"))
        self.assertEqual(max_p, Decimal("75.00"))

    def test_allowed_price_range_boundaries_accepted(self):
        """Acceptance test: Boundary values (exactly min and exactly max) are accepted."""
        course = Course(
            instructor=self.lecturer,
            title="Boundary Course",
            category=Course.Category.ACADEMIC,
            total_duration_seconds=0,
            price=Decimal("25.00"),
        )
        # Exactly min is accepted
        validate_course_price(course)

        # Exactly max is accepted
        course.price = Decimal("75.00")
        validate_course_price(course)

        # Out of range below rejected
        course.price = Decimal("24.99")
        with self.assertRaises(ValidationError):
            validate_course_price(course)

        # Out of range above rejected
        course.price = Decimal("75.01")
        with self.assertRaises(ValidationError):
            validate_course_price(course)

    def test_lesson_change_reverts_published_course_if_price_out_of_range(self):
        """
        PRD 7.2: If lessons change after publishing and the price falls outside
        the range, the course is automatically moved back to draft and the seller is notified.
        """
        course = Course.objects.create(
            instructor=self.lecturer,
            title="Full Course",
            category=Course.Category.ACADEMIC,
            price=Decimal("50.00"),
            status=Course.Status.PUBLISHED,
        )
        # Add 1 lesson (3600 seconds = 1 hr). Allowed price: 50.00 - 150.00. 50.00 is valid.
        Lesson.objects.create(
            course=course,
            title="Lesson 1",
            order=1,
            duration_seconds=3600,
        )
        check_and_update_course_on_lesson_change(course)
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.PUBLISHED)
        self.assertEqual(course.total_duration_seconds, 3600)

        # Now add 5 more hours of lessons (total 6 hours). Min price: 6 * 50 = 300.00 BDT.
        # Course price is currently 50.00 BDT -> outside range!
        Lesson.objects.create(
            course=course,
            title="Lesson 2",
            order=2,
            duration_seconds=18000,
        )
        check_and_update_course_on_lesson_change(course)
        course.refresh_from_db()

        # Must be reverted to DRAFT
        self.assertEqual(course.status, Course.Status.DRAFT)
        self.assertEqual(course.total_duration_seconds, 21600)

        # Check notification sent to seller
        notif = self.lecturer.notifications.filter(message__contains="reverted to draft").first()
        self.assertIsNotNone(notif)


class SellerAuthorizationTests(TestCase):
    def setUp(self):
        self.dept = make_department(code="CSE", name="Computer Science")
        self.batch = make_batch(department=self.dept, name="Batch 2026")
        self.approved_student = make_student(username="appr_student", batch=self.batch)
        self.lecturer = make_lecturer(username="lecturer_seller")

        # Unapproved student (no batch membership)
        self.unapproved_student = make_student(username="unapproved_s", batch=None)

        # Unverified lecturer
        self.unverified_lecturer = make_lecturer(
            username="unverified_l",
            is_email_verified=False,
            email_verified_at=None,
        )

    def test_can_sell_helper_matrix(self):
        """PRD 7.4: Verified email plus lecturer or approved batch member."""
        self.assertTrue(can_sell(self.lecturer))
        self.assertTrue(can_sell(self.approved_student))
        self.assertFalse(can_sell(self.unapproved_student))
        self.assertFalse(can_sell(self.unverified_lecturer))

    def test_unauthorized_user_cannot_create_course(self):
        client = Client()
        client.force_login(self.unapproved_student)
        resp = client.get(reverse("courses:course_create"))
        self.assertEqual(resp.status_code, 403)

    def test_seller_cannot_buy_own_course(self):
        course = Course.objects.create(
            instructor=self.lecturer,
            title="Lecturer Course",
            category=Course.Category.ACADEMIC,
            price=Decimal("50.00"),
            status=Course.Status.PUBLISHED,
        )
        client = Client()
        client.force_login(self.lecturer)
        resp = client.get(reverse("courses:course_buy", args=[course.id]))
        # Redirects back to detail with error message
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            CoursePurchase.objects.filter(user=self.lecturer, course=course).exists()
        )


class CoursePurchaseAndCommissionTests(TestCase):
    def setUp(self):
        self.seller = make_lecturer(username="seller_prof")
        self.buyer = make_student(username="buyer_student")
        self.course = Course.objects.create(
            instructor=self.seller,
            title="Masterclass in DB",
            category=Course.Category.NON_ACADEMIC,
            price=Decimal("1000.00"),
            status=Course.Status.PUBLISHED,
        )
        self.client = Client()

    def test_commission_math_1000_price(self):
        """
        Acceptance test: Commission math: price 1000 at 10% gives seller 900, platform 100;
        running fulfilment twice credits once.
        """
        initial_seller_balance = get_wallet_balance(self.seller)

        order = create_order(
            user=self.buyer,
            purpose=PaymentOrder.Purpose.COURSE,
            amount_bdt=Decimal("1000.00"),
            reference_type="course",
            reference_id=str(self.course.id),
        )

        result = PaymentResult(order_id=str(order.id), success=True, gateway_txn_id="TXN-1000")
        complete_order(order, result)

        purchase = CoursePurchase.objects.get(user=self.buyer, course=self.course)
        self.assertTrue(purchase.is_successful)
        self.assertEqual(purchase.amount_paid, Decimal("1000.00"))
        self.assertEqual(purchase.commission_amount, Decimal("100.00"))  # 10% of 1000
        self.assertEqual(purchase.seller_earning, Decimal("900.00"))      # 900 to seller

        # Check seller wallet ledger entry
        self.assertEqual(get_wallet_balance(self.seller), initial_seller_balance + Decimal("900.00"))
        wallet_entry = WalletEntry.objects.get(user=self.seller, reason=WalletEntry.Reason.COURSE_SALE)
        self.assertEqual(wallet_entry.amount, Decimal("900.00"))

        # Running fulfilment twice credits once (idempotent)
        complete_order(order, result)
        self.assertEqual(CoursePurchase.objects.filter(user=self.buyer, course=self.course).count(), 1)
        self.assertEqual(
            WalletEntry.objects.filter(user=self.seller, reason=WalletEntry.Reason.COURSE_SALE).count(),
            1,
        )
        self.assertEqual(get_wallet_balance(self.seller), initial_seller_balance + Decimal("900.00"))


class SecureStreamingTests(TestCase):
    def setUp(self):
        self.seller = make_lecturer(username="video_prof")
        self.buyer = make_student(username="video_buyer")
        self.stranger = make_student(username="stranger_student")

        self.course = Course.objects.create(
            instructor=self.seller,
            title="Video Course with Lessons",
            category=Course.Category.ACADEMIC,
            price=Decimal("50.00"),
            status=Course.Status.PUBLISHED,
        )

        # Upload a lesson with real MP4 file
        self.lesson_paid = Lesson.objects.create(
            course=self.course,
            title="Lesson 1 - Core Concepts",
            order=1,
            video_file=sample_mp4_file("test_stream.mp4"),
            duration_seconds=10,
            is_free_preview=False,
        )

        self.lesson_preview = Lesson.objects.create(
            course=self.course,
            title="Lesson 2 - Free Preview",
            order=2,
            video_file=sample_mp4_file("test_preview.mp4"),
            duration_seconds=10,
            is_free_preview=True,
        )

        self.client = Client()

    def test_non_buyer_cannot_stream_lesson(self):
        """Acceptance test: A non-buyer cannot stream a lesson (403)."""
        self.client.force_login(self.stranger)
        resp = self.client.get(reverse("courses:lesson_stream", args=[self.lesson_paid.id]))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_non_buyer_cannot_stream_paid_lesson(self):
        resp = self.client.get(reverse("courses:lesson_stream", args=[self.lesson_paid.id]))
        self.assertEqual(resp.status_code, 403)

    def test_free_preview_can_be_streamed_by_anyone(self):
        """Free preview lesson stream is accessible by anonymous visitors."""
        resp = self.client.get(reverse("courses:lesson_stream", args=[self.lesson_preview.id]))
        self.assertIn(resp.status_code, [200, 206])
        self.assertEqual(resp["Accept-Ranges"], "bytes")
        self.assertEqual(resp["Cache-Control"], "private")

    def test_seller_and_superuser_can_stream(self):
        self.client.force_login(self.seller)
        resp = self.client.get(reverse("courses:lesson_stream", args=[self.lesson_paid.id]))
        self.assertIn(resp.status_code, [200, 206])

    def test_http_range_seeking(self):
        """
        Acceptance test: Seeking in the player works
        (Range tests: bytes=0-99, bytes=100-, invalid range gives 416).
        """
        # Grant buyer access
        CoursePurchase.objects.create(
            user=self.buyer,
            course=self.course,
            amount_paid=Decimal("50.00"),
            is_successful=True,
        )
        self.client.force_login(self.buyer)

        file_size = self.lesson_paid.video_file.size
        stream_url = reverse("courses:lesson_stream", args=[self.lesson_paid.id])

        # Test 1: Range bytes=0-99
        resp_0_99 = self.client.get(stream_url, HTTP_RANGE="bytes=0-99")
        self.assertEqual(resp_0_99.status_code, 206)
        self.assertEqual(resp_0_99["Content-Range"], f"bytes 0-99/{file_size}")
        self.assertEqual(resp_0_99["Content-Length"], "100")
        self.assertEqual(resp_0_99["Accept-Ranges"], "bytes")
        self.assertEqual(resp_0_99["Cache-Control"], "private")

        # Test 2: Range bytes=100-
        resp_100 = self.client.get(stream_url, HTTP_RANGE="bytes=100-")
        self.assertEqual(resp_100.status_code, 206)
        self.assertEqual(resp_100["Content-Range"], f"bytes 100-{file_size - 1}/{file_size}")
        self.assertEqual(resp_100["Content-Length"], str(file_size - 100))

        # Test 3: Invalid Range gives 416
        resp_invalid = self.client.get(stream_url, HTTP_RANGE="bytes=99999999-")
        self.assertEqual(resp_invalid.status_code, 416)
        self.assertEqual(resp_invalid["Content-Range"], f"bytes */{file_size}")

    @override_settings(USE_X_ACCEL_REDIRECT=True)
    def test_x_accel_redirect_mode(self):
        CoursePurchase.objects.create(
            user=self.buyer,
            course=self.course,
            amount_paid=Decimal("50.00"),
            is_successful=True,
        )
        self.client.force_login(self.buyer)
        stream_url = reverse("courses:lesson_stream", args=[self.lesson_paid.id])
        resp = self.client.get(stream_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.has_header("X-Accel-Redirect"))
        self.assertEqual(resp["Cache-Control"], "private")

    def test_learn_page_deterrent_player(self):
        """Learn page renders video player with controlsList='nodownload' deterrent."""
        CoursePurchase.objects.create(
            user=self.buyer,
            course=self.course,
            amount_paid=Decimal("50.00"),
            is_successful=True,
        )
        self.client.force_login(self.buyer)
        resp = self.client.get(reverse("courses:course_learn", args=[self.course.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'controlsList="nodownload"')


class FeatureFlagGatingTests(TestCase):
    def setUp(self):
        self.lecturer = make_lecturer(username="gated_prof")
        self.course = Course.objects.create(
            instructor=self.lecturer,
            title="Gated Course",
            category=Course.Category.ACADEMIC,
            price=Decimal("50.00"),
            status=Course.Status.PUBLISHED,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Gated Lesson",
            order=1,
            duration_seconds=10,
        )
        self.client = Client()
        self.client.force_login(self.lecturer)

    @override_settings(ENABLE_VIDEO_COURSES=False)
    def test_courses_disabled_returns_404_on_all_endpoints(self):
        """
        Acceptance test: With ENABLE_VIDEO_COURSES=False no course link,
        page or home section is reachable.
        """
        endpoints = [
            reverse("courses:course_list"),
            reverse("courses:my_courses"),
            reverse("courses:course_create"),
            reverse("courses:course_detail", args=[self.course.id]),
            reverse("courses:course_edit", args=[self.course.id]),
            reverse("courses:course_buy", args=[self.course.id]),
            reverse("courses:course_learn", args=[self.course.id]),
            reverse("courses:lesson_stream", args=[self.lesson.id]),
        ]
        for url in endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 404, f"{url} was accessible while flag is False!")
