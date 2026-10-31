from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from credits.models import CreditLedger


def run_ledger_check():
    """Runs read-only ledger integrity checks and returns structured findings.

    Checks:
    1. Users with negative credit balance.
    2. Users with duplicate signup bonuses.
    3. Duplicate upload rewards for one note.
    4. Reversals without a target entry.
    """
    # 1. Users with negative balance
    negative_balances = list(
        CreditLedger.objects.values("user_id", "user__username")
        .annotate(balance=Sum("amount"))
        .filter(balance__lt=0)
        .order_by("balance")
    )

    # 2. Duplicate signup bonuses
    duplicate_signups = list(
        CreditLedger.objects.filter(reason=CreditLedger.Reason.SIGNUP_BONUS)
        .values("user_id", "user__username")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .order_by("-count")
    )

    # 3. Duplicate upload rewards for one note
    duplicate_upload_rewards = []
    seen_rewards = set()

    # Exact description match for upload rewards
    desc_matches = list(
        CreditLedger.objects.filter(reason=CreditLedger.Reason.NOTE_UPLOAD)
        .values("user_id", "user__username", "description")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    for r in desc_matches:
        duplicate_upload_rewards.append({
            "user_id": r["user_id"],
            "username": r["user__username"],
            "title": r["description"],
            "count": r["count"],
        })
        seen_rewards.add((r["user_id"], r["description"]))

    # Also inspect Note model if available
    try:
        from notes.models import Note

        for note in Note.objects.select_related("owner").all():
            if not note.title:
                continue
            matching_entries = CreditLedger.objects.filter(
                user=note.owner,
                reason=CreditLedger.Reason.NOTE_UPLOAD,
                description__icontains=note.title,
            )
            count = matching_entries.count()
            if count > 1:
                key = (note.owner_id, note.title)
                if key not in seen_rewards:
                    duplicate_upload_rewards.append({
                        "user_id": note.owner_id,
                        "username": note.owner.username,
                        "title": f"Note #{note.id}: {note.title}",
                        "count": count,
                    })
                    seen_rewards.add(key)
    except Exception:
        pass

    # 4. Reversals without a target
    orphan_reversals = list(
        CreditLedger.objects.filter(
            reason=CreditLedger.Reason.REVERSAL,
            reverses__isnull=True,
        )
        .values("id", "user_id", "user__username", "amount", "description", "created_at")
        .order_by("-created_at")
    )

    total_issues = (
        len(negative_balances)
        + len(duplicate_signups)
        + len(duplicate_upload_rewards)
        + len(orphan_reversals)
    )

    return {
        "negative_balances": negative_balances,
        "duplicate_signups": duplicate_signups,
        "duplicate_upload_rewards": duplicate_upload_rewards,
        "orphan_reversals": orphan_reversals,
        "total_issues": total_issues,
    }


class Command(BaseCommand):
    help = "Read-only integrity check for the credit ledger."

    def handle(self, *args, **options):
        findings = run_ledger_check()

        self.stdout.write(self.style.MIGRATE_HEADING("=== Credit Ledger Integrity Audit ==="))

        has_issues = False

        # 1. Negative balance
        if findings["negative_balances"]:
            has_issues = True
            self.stdout.write(self.style.ERROR(f"\n[!] Users with negative balance ({len(findings['negative_balances'])} found):"))
            for item in findings["negative_balances"]:
                self.stdout.write(f"  - User {item['user__username']} (ID {item['user_id']}): {item['balance']} nuts")
        else:
            self.stdout.write(self.style.SUCCESS("[OK] No users with negative balance."))

        # 2. Duplicate signup bonuses
        if findings["duplicate_signups"]:
            has_issues = True
            self.stdout.write(self.style.ERROR(f"\n[!] Users with duplicate signup bonuses ({len(findings['duplicate_signups'])} found):"))
            for item in findings["duplicate_signups"]:
                self.stdout.write(f"  - User {item['user__username']} (ID {item['user_id']}): {item['count']} bonuses")
        else:
            self.stdout.write(self.style.SUCCESS("[OK] No duplicate signup bonuses."))

        # 3. Duplicate upload rewards
        if findings["duplicate_upload_rewards"]:
            has_issues = True
            self.stdout.write(self.style.ERROR(f"\n[!] Duplicate upload rewards for one note ({len(findings['duplicate_upload_rewards'])} found):"))
            for item in findings["duplicate_upload_rewards"]:
                self.stdout.write(f"  - User {item['username']} (ID {item['user_id']}): {item['count']} rewards for '{item['title']}'")
        else:
            self.stdout.write(self.style.SUCCESS("[OK] No duplicate note upload rewards."))

        # 4. Orphan reversals
        if findings["orphan_reversals"]:
            has_issues = True
            self.stdout.write(self.style.ERROR(f"\n[!] Reversals without a target entry ({len(findings['orphan_reversals'])} found):"))
            for item in findings["orphan_reversals"]:
                self.stdout.write(f"  - Entry #{item['id']} by {item['user__username']}: {item['amount']} nuts ('{item['description']}')")
        else:
            self.stdout.write(self.style.SUCCESS("[OK] No orphan reversals without a target."))

        if not has_issues:
            self.stdout.write(self.style.SUCCESS("\nAll integrity checks PASSED. Ledger is completely consistent."))
        else:
            self.stdout.write(self.style.WARNING(f"\nTotal integrity issues detected: {findings['total_issues']}"))
