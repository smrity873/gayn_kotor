from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from notes.services import process_review_deadlines, publish_overdue_notes


class Command(BaseCommand):
    help = "Run review deadline reminders, escalations, and auto-publishing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate execution without persisting changes or sending notifications.",
        )
        parser.add_argument(
            "--now",
            type=str,
            default=None,
            help="ISO datetime override for testing/demos (e.g. 2026-11-05T12:00:00Z).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now_str = options["now"]

        now = timezone.now()
        if now_str:
            dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                now = timezone.make_aware(dt)
            else:
                now = dt

        self.stdout.write(f"Executing review deadlines at {now.isoformat()} (dry_run={dry_run})...")

        if dry_run:
            with transaction.atomic():
                updated = process_review_deadlines(now=now)
                overdue = publish_overdue_notes(now=now)
                transaction.set_rollback(True)
            self.stdout.write(
                self.style.SUCCESS(
                    f"[DRY RUN] Completed. Simulated {updated} deadline actions and {overdue} overdue note publications."
                )
            )
        else:
            updated = process_review_deadlines(now=now)
            overdue = publish_overdue_notes(now=now)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Completed. Executed {updated} deadline actions and {overdue} overdue note publications."
                )
            )

