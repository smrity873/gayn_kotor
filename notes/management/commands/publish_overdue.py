from django.core.management.base import BaseCommand

from notes.services import publish_overdue_notes


class Command(BaseCommand):
    help = "Publish notes that nobody reviewed in time (as unverified)."

    def handle(self, *args, **options):
        count = publish_overdue_notes()
        self.stdout.write(self.style.SUCCESS(f"{count} note(s) published as unverified."))