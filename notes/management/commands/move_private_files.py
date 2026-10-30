import os
from pathlib import Path
import shutil
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand
from notes.models import Note


class Command(BaseCommand):
    help = "Move existing note PDFs and previews from public media to private media storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what files would be moved without modifying disk or database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        media_root = Path(settings.MEDIA_ROOT)
        private_root = Path(settings.PRIVATE_MEDIA_ROOT)

        if dry_run:
            self.stdout.write(self.style.WARNING("Running move_private_files in DRY-RUN mode."))
        else:
            private_root.mkdir(parents=True, exist_ok=True)

        notes_count = 0
        files_moved = 0
        previews_moved = 0
        copied_sources = set()

        for note in Note.objects.all().order_by("id"):
            notes_count += 1
            updated_fields = []

            # Check file
            if note.file and note.file.name:
                old_file_rel = note.file.name
                old_file_path = media_root / old_file_rel
                source_to_use = None

                if old_file_path.exists():
                    source_to_use = old_file_path
                elif not (private_root / old_file_rel).exists():
                    # Check if file was already moved into private_root by previous note
                    for p in private_root.glob("notes/*"):
                        if p.is_file():
                            source_to_use = p
                            break

                if source_to_use:
                    ext = os.path.splitext(old_file_rel)[1].lower() or ".pdf"
                    new_file_rel = f"notes/{uuid.uuid4()}{ext}"
                    target_file_path = private_root / new_file_rel

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Note #{note.id} file: would copy '{source_to_use}' to '{target_file_path}'"
                        )
                    else:
                        target_file_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(source_to_use), str(target_file_path))
                        copied_sources.add(source_to_use)
                        note.file.name = new_file_rel
                        updated_fields.append("file")
                        self.stdout.write(
                            self.style.SUCCESS(f"Note #{note.id} file: moved/copied to '{target_file_path}'")
                        )
                    files_moved += 1

            # Check preview
            if note.preview and note.preview.name:
                old_prev_rel = note.preview.name
                old_prev_path = media_root / old_prev_rel
                source_to_use = None

                if old_prev_path.exists():
                    source_to_use = old_prev_path
                elif not (private_root / old_prev_rel).exists():
                    for p in private_root.glob("previews/*"):
                        if p.is_file():
                            source_to_use = p
                            break

                if source_to_use:
                    ext = os.path.splitext(old_prev_rel)[1].lower() or ".jpg"
                    new_prev_rel = f"previews/{uuid.uuid4()}{ext}"
                    target_prev_path = private_root / new_prev_rel

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Note #{note.id} preview: would copy '{source_to_use}' to '{target_prev_path}'"
                        )
                    else:
                        target_prev_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(source_to_use), str(target_prev_path))
                        copied_sources.add(source_to_use)
                        note.preview.name = new_prev_rel
                        updated_fields.append("preview")
                        self.stdout.write(
                            self.style.SUCCESS(f"Note #{note.id} preview: moved/copied to '{target_prev_path}'")
                        )
                    previews_moved += 1

            if updated_fields and not dry_run:
                note.save(update_fields=updated_fields)

        # Remove copied source files in media_root to prevent public access
        if not dry_run:
            for src in copied_sources:
                if str(src).startswith(str(media_root)) and src.exists():
                    try:
                        src.unlink()
                    except Exception:
                        pass

        mode_str = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode_str}Complete. Scanned {notes_count} note(s). Files to move/moved: {files_moved}, Previews to move/moved: {previews_moved}."
            )
        )
