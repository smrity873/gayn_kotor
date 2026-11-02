import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from campus.models import Batch, BatchMembership, Department
from courses.models import Course, Lesson, PricingRule, CoursePurchase
from credits.models import CreditLedger
from credits.services import add_entry
from notes.models import Note, NoteAppeal, NoteDownload, NoteRating, NoteReport
from payments.models import PaymentOrder, WalletEntry
from payments.services import complete_order, create_order
from payments.gateways.base import PaymentResult
from swaps.models import SkillPost, SwapSession


def dummy_pdf():
    return ContentFile(b"%PDF-1.4 demo file content", name="demo_notes.pdf")


def dummy_mp4():
    mp4_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
    if os.path.exists(mp4_path):
        with open(mp4_path, "rb") as f:
            return ContentFile(f.read(), name="demo_lesson.mp4")
    return ContentFile(b"fake mp4 video bytes", name="demo_lesson.mp4")


class Command(BaseCommand):
    help = "Seed demo data for testing, development, and presentation (idempotent, DEBUG=True only)."

    def handle(self, *args, **options):
        if not getattr(settings, "DEBUG", False):
            raise CommandError("seed_demo refuses to run when DEBUG=False (development mode only).")

        self.stdout.write("Seeding demo data...")

        now = timezone.now()
        password = "Password123!"

        # -------------------------------------------------------------
        # 1. Departments
        # -------------------------------------------------------------
        cse, _ = Department.objects.get_or_create(code="CSE", defaults={"name": "Computer Science & Engineering"})
        eee, _ = Department.objects.get_or_create(code="EEE", defaults={"name": "Electrical & Electronic Engineering"})
        bba, _ = Department.objects.get_or_create(code="BBA", defaults={"name": "Business Administration"})

        # -------------------------------------------------------------
        # 2. Users & Staff
        # -------------------------------------------------------------
        admin_user, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@campus.edu",
                "id_number": "ADMIN-0001",
                "is_staff": True,
                "is_superuser": True,
                "role": User.Role.LECTURER,
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        admin_user.set_password(password)
        admin_user.save()

        # Lecturers
        prof_rahim, _ = User.objects.get_or_create(
            username="prof.rahim",
            defaults={
                "email": "rahim@campus.edu",
                "role": User.Role.LECTURER,
                "id_number": "LEC-0001",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        prof_rahim.set_password(password)
        prof_rahim.save()

        prof_karim, _ = User.objects.get_or_create(
            username="prof.karim",
            defaults={
                "email": "karim@campus.edu",
                "role": User.Role.LECTURER,
                "id_number": "LEC-0002",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        prof_karim.set_password(password)
        prof_karim.save()

        # -------------------------------------------------------------
        # 3. Batches & Class Teachers
        # -------------------------------------------------------------
        batch_cse, _ = Batch.objects.get_or_create(
            department=cse,
            name="Batch 2023",
            defaults={"class_teacher": prof_rahim},
        )
        batch_cse.class_teacher = prof_rahim
        batch_cse.save()

        batch_eee, _ = Batch.objects.get_or_create(
            department=eee,
            name="Batch 2024",
            defaults={"class_teacher": prof_karim},
        )
        batch_eee.class_teacher = prof_karim
        batch_eee.save()

        # -------------------------------------------------------------
        # 4. CRs and Students
        # -------------------------------------------------------------
        cr_cse, _ = User.objects.get_or_create(
            username="cr.cse",
            defaults={
                "email": "cr.cse@campus.edu",
                "role": User.Role.STUDENT,
                "id_number": "100000000000001",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        cr_cse.set_password(password)
        cr_cse.save()
        BatchMembership.objects.get_or_create(
            user=cr_cse, batch=batch_cse,
            defaults={"is_cr": True, "status": BatchMembership.Status.APPROVED}
        )

        student_alice, _ = User.objects.get_or_create(
            username="student.alice",
            defaults={
                "email": "alice@campus.edu",
                "role": User.Role.STUDENT,
                "id_number": "100000000000002",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        student_alice.set_password(password)
        student_alice.save()
        BatchMembership.objects.get_or_create(
            user=student_alice, batch=batch_cse,
            defaults={"status": BatchMembership.Status.APPROVED}
        )

        student_bob, _ = User.objects.get_or_create(
            username="student.bob",
            defaults={
                "email": "bob@campus.edu",
                "role": User.Role.STUDENT,
                "id_number": "100000000000003",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        student_bob.set_password(password)
        student_bob.save()
        BatchMembership.objects.get_or_create(
            user=student_bob, batch=batch_cse,
            defaults={"status": BatchMembership.Status.APPROVED}
        )

        student_charlie, _ = User.objects.get_or_create(
            username="student.charlie",
            defaults={
                "email": "charlie@campus.edu",
                "role": User.Role.STUDENT,
                "id_number": "100000000000004",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        student_charlie.set_password(password)
        student_charlie.save()
        BatchMembership.objects.get_or_create(
            user=student_charlie, batch=batch_eee,
            defaults={"status": BatchMembership.Status.APPROVED}
        )

        student_pending, _ = User.objects.get_or_create(
            username="student.pending",
            defaults={
                "email": "pending@campus.edu",
                "role": User.Role.STUDENT,
                "id_number": "100000000000005",
                "is_email_verified": True,
                "email_verified_at": now,
            },
        )
        student_pending.set_password(password)
        student_pending.save()
        BatchMembership.objects.get_or_create(
            user=student_pending, batch=batch_cse,
            defaults={"status": BatchMembership.Status.PENDING}
        )

        # Grant initial credits
        if not student_alice.ledger.exists():
            add_entry(student_alice, 50, CreditLedger.Reason.SIGNUP_BONUS, "Welcome nuts bonus")
        if not student_bob.ledger.exists():
            add_entry(student_bob, 30, CreditLedger.Reason.SIGNUP_BONUS, "Welcome nuts bonus")

        # -------------------------------------------------------------
        # 5. Notes of Different Ages (Demonstrates escalation/reminders)
        # -------------------------------------------------------------
        # Note 1: Published & popular (10 days old)
        note_published, _ = Note.objects.get_or_create(
            title="Data Structures & Algorithms Comprehensive Notes",
            defaults={
                "owner": student_alice,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE201",
                "semester": 3,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.APPROVED,
                "file": dummy_pdf(),
                "created_at": now - timedelta(days=10),
            },
        )
        NoteDownload.objects.get_or_create(user=student_bob, note=note_published)
        NoteRating.objects.get_or_create(
            user=student_bob, note=note_published,
            defaults={"rating": 5, "review": "Exceptional notes, helped me ace the midterm!"}
        )

        # Note 2: Fresh pending note (0 days old)
        Note.objects.get_or_create(
            title="Database Management Systems Lab Notes",
            defaults={
                "owner": student_bob,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE202",
                "semester": 3,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.PENDING,
                "file": dummy_pdf(),
                "created_at": now,
            },
        )

        # Note 3: 2-day-old pending note (triggers CR reminder on send_reminders)
        note_2d, _ = Note.objects.get_or_create(
            title="Computer Networks Chapter 1-4",
            defaults={
                "owner": student_alice,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE301",
                "semester": 5,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.PENDING,
                "file": dummy_pdf(),
            },
        )
        Note.objects.filter(pk=note_2d.pk).update(created_at=now - timedelta(days=2, hours=1))

        # Note 4: 4-day-old pending note (escalated to Class Teacher prof.rahim)
        note_4d, _ = Note.objects.get_or_create(
            title="Operating Systems Memory Virtualization",
            defaults={
                "owner": student_bob,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE302",
                "semester": 5,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.PENDING,
                "file": dummy_pdf(),
            },
        )
        Note.objects.filter(pk=note_4d.pk).update(created_at=now - timedelta(days=4, hours=1))

        # Note 5: 8-day-old pending note (past auto-publish threshold)
        note_8d, _ = Note.objects.get_or_create(
            title="Discrete Mathematics Graph Theory",
            defaults={
                "owner": student_alice,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE103",
                "semester": 2,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.PENDING,
                "file": dummy_pdf(),
            },
        )
        Note.objects.filter(pk=note_8d.pk).update(created_at=now - timedelta(days=8, hours=1))

        # Note 6: Flagged note with appeal
        note_flagged, _ = Note.objects.get_or_create(
            title="Microprocessors Architecture Diagrams",
            defaults={
                "owner": student_alice,
                "department": cse,
                "batch": batch_cse,
                "course_code": "CSE304",
                "semester": 5,
                "visibility": Note.Visibility.PUBLIC,
                "status": Note.Status.FLAGGED,
                "file": dummy_pdf(),
            },
        )
        NoteAppeal.objects.get_or_create(
            note=note_flagged,
            user=student_alice,
            defaults={"message": "This file contains strictly original notes, not textbook copies."},
        )

        # -------------------------------------------------------------
        # 6. Skill Swap Posts & Sessions in Each State
        # -------------------------------------------------------------
        post_python, _ = SkillPost.objects.get_or_create(
            user=student_alice,
            kind=SkillPost.Kind.OFFER,
            skill_name="Python & Pandas",
            defaults={"description": "Can help with data processing and Python assignments."},
        )

        post_circuit, _ = SkillPost.objects.get_or_create(
            user=student_charlie,
            kind=SkillPost.Kind.OFFER,
            skill_name="AC Circuit Analysis",
            defaults={"description": "Can teach RLC circuits and phasor diagrams."},
        )

        # Session: Scheduled (active meeting link)
        SwapSession.objects.get_or_create(
            post=post_python,
            teacher=student_alice,
            learner=student_bob,
            skill_name="Python & Pandas",
            defaults={
                "status": SwapSession.Status.SCHEDULED,
                "proposed_time": now + timedelta(days=1),
                "meeting_link": "https://meet.google.com/demo-swap-link",
            },
        )

        # Session: Completed
        SwapSession.objects.get_or_create(
            post=post_circuit,
            teacher=student_charlie,
            learner=student_alice,
            skill_name="AC Circuit Analysis",
            defaults={
                "status": SwapSession.Status.COMPLETED,
                "proposed_time": now - timedelta(days=2),
                "meeting_link": "https://meet.google.com/past-demo-link",
            },
        )

        # -------------------------------------------------------------
        # 7. Video Courses, Lessons & Wallet
        # -------------------------------------------------------------
        PricingRule.objects.get_or_create(
            category=Course.Category.ACADEMIC,
            defaults={"min_per_hour": Decimal("50.00"), "max_per_hour": Decimal("150.00")},
        )
        PricingRule.objects.get_or_create(
            category=Course.Category.NON_ACADEMIC,
            defaults={"min_per_hour": Decimal("200.00"), "max_per_hour": Decimal("600.00")},
        )

        course_published, _ = Course.objects.get_or_create(
            title="Complete Web Development with Django & PostgreSQL",
            defaults={
                "instructor": prof_rahim,
                "description": "Learn to architect and deploy modern, robust web apps with clean architecture.",
                "category": Course.Category.ACADEMIC,
                "price": Decimal("50.00"),
                "status": Course.Status.PUBLISHED,
                "total_duration_seconds": 600,
            },
        )
        Lesson.objects.get_or_create(
            course=course_published,
            order=1,
            defaults={
                "title": "Course Overview & Project Structure",
                "duration_seconds": 300,
                "is_free_preview": True,
                "video_file": dummy_mp4(),
            },
        )
        Lesson.objects.get_or_create(
            course=course_published,
            order=2,
            defaults={
                "title": "Django ORM & PostgreSQL Best Practices",
                "duration_seconds": 300,
                "is_free_preview": False,
                "video_file": dummy_mp4(),
            },
        )

        # Course purchase & wallet credit
        if not CoursePurchase.objects.filter(course=course_published, user=student_alice).exists():
            order = create_order(
                user=student_alice,
                purpose=PaymentOrder.Purpose.COURSE,
                amount_bdt=Decimal("50.00"),
                reference_type="course",
                reference_id=str(course_published.id),
            )
            complete_order(order, PaymentResult(order_id=str(order.id), success=True, gateway_txn_id="DEMO-TXN-1"))

        # Course 2: Draft
        Course.objects.get_or_create(
            title="Advanced System Design & Scalability",
            defaults={
                "instructor": prof_rahim,
                "description": "Draft course on high-scale distributed systems.",
                "category": Course.Category.NON_ACADEMIC,
                "price": Decimal("200.00"),
                "status": Course.Status.DRAFT,
                "total_duration_seconds": 0,
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo database successfully seeded!"))
        self.stdout.write(
            "Demo accounts created (Password for all: Password123!):\n"
            "  Admin:        admin (admin@campus.edu)\n"
            "  Lecturers:    prof.rahim, prof.karim\n"
            "  CRs:          cr.cse\n"
            "  Students:     student.alice, student.bob, student.charlie, student.pending"
        )
