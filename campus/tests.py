from django.test import Client, TestCase
from django.urls import reverse

from campus.models import BatchMembership
from core.testing import make_batch, make_department, make_lecturer, make_student
from notifications.models import Notification


class CampusCRManagementTests(TestCase):
    def setUp(self):
        self.dept = make_department(name="Computer Science & Engineering", code="CSE")
        self.teacher = make_lecturer(username="prof_smith")
        self.other_teacher = make_lecturer(username="prof_jones")
        self.batch = make_batch(department=self.dept, name="2024", class_teacher=self.teacher)

        self.student1 = make_student(username="alice", batch=self.batch)
        self.student2 = make_student(username="bob", batch=self.batch)

        self.m1 = BatchMembership.objects.get(user=self.student1, batch=self.batch)
        self.m2 = BatchMembership.objects.get(user=self.student2, batch=self.batch)
        self.client = Client(raise_request_exception=False)

    def test_teacher_appoint_initial_cr_via_change_cr(self):
        self.client.force_login(self.teacher)
        res = self.client.post(
            reverse("campus:change_cr", args=[self.batch.id]),
            {"membership_id": str(self.m1.id)},
        )
        self.assertRedirects(res, reverse("campus:manage"))
        self.m1.refresh_from_db()
        self.assertTrue(self.m1.is_cr)
        self.assertTrue(Notification.objects.filter(user=self.student1).exists())

    def test_teacher_change_cr_transfers_from_old_to_new_cr(self):
        # First appoint student1 as CR
        self.m1.is_cr = True
        self.m1.save()

        # Teacher changes CR to student2
        self.client.force_login(self.teacher)
        res = self.client.post(
            reverse("campus:change_cr", args=[self.batch.id]),
            {"membership_id": str(self.m2.id)},
        )
        self.assertRedirects(res, reverse("campus:manage"))

        self.m1.refresh_from_db()
        self.m2.refresh_from_db()

        self.assertFalse(self.m1.is_cr, "Old CR should have is_cr set to False")
        self.assertTrue(self.m2.is_cr, "New CR should have is_cr set to True")

        # Check notifications
        self.assertTrue(
            Notification.objects.filter(user=self.student1, message__icontains="no longer the CR").exists()
        )
        self.assertTrue(
            Notification.objects.filter(user=self.student2, message__icontains="now the CR").exists()
        )

    def test_teacher_clears_cr(self):
        self.m1.is_cr = True
        self.m1.save()

        self.client.force_login(self.teacher)
        res = self.client.post(
            reverse("campus:change_cr", args=[self.batch.id]),
            {"membership_id": "none"},
        )
        self.assertRedirects(res, reverse("campus:manage"))
        self.m1.refresh_from_db()
        self.assertFalse(self.m1.is_cr)

    def test_non_class_teacher_cannot_change_cr(self):
        self.client.force_login(self.other_teacher)
        res = self.client.post(
            reverse("campus:change_cr", args=[self.batch.id]),
            {"membership_id": str(self.m1.id)},
        )
        self.assertEqual(res.status_code, 403)
        self.m1.refresh_from_db()
        self.assertFalse(self.m1.is_cr)

    def test_student_cannot_change_cr(self):
        self.client.force_login(self.student1)
        res = self.client.post(
            reverse("campus:change_cr", args=[self.batch.id]),
            {"membership_id": str(self.m1.id)},
        )
        self.assertEqual(res.status_code, 403)

    def test_membership_action_make_cr_transfers_cleanly(self):
        self.m1.is_cr = True
        self.m1.save()

        self.client.force_login(self.teacher)
        res = self.client.post(
            reverse("campus:membership_action", args=[self.m2.id]),
            {"action": "make_cr"},
        )
        self.assertRedirects(res, reverse("campus:manage"))

        self.m1.refresh_from_db()
        self.m2.refresh_from_db()

        self.assertFalse(self.m1.is_cr)
        self.assertTrue(self.m2.is_cr)
