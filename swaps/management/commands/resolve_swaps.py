from django.core.management.base import BaseCommand

from swaps.services import resolve_all_swaps


class Command(BaseCommand):
    help = "Applies time-based rules for skill swaps: dispute window expiration, auto-resolution, and 7-day stale session expiry."

    def handle(self, *args, **options):
        self.stdout.write("Running resolve_swaps engine...")
        resolved_count = resolve_all_swaps()
        self.stdout.write(self.style.SUCCESS(f"Successfully processed sessions. {resolved_count} status transitions resolved."))
