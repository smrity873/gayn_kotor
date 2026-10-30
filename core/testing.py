import uuid
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from campus.models import Batch, BatchMembership, Department
from credits.models import CreditLedger
from credits.services import add_entry
from notes.models import Note

_counter = 0


def _seq():
    global _counter
    _counter += 1
    return _counter


def make_department(name=None, code=None):
    seq = _seq()
    name = name or f"Department {seq}"
    code = code or f"D{seq}"
    return Department.objects.create(name=name, code=code)


def make_batch(department=None, name=None, class_teacher=None):
    if department is None:
        department = make_department()
    seq = _seq()
    name = name or f"Batch {seq}"
    return Batch.objects.create(department=department, name=name, class_teacher=class_teacher)


def make_student(batch=None, cr=False, username=None, **kwargs):
    seq = _seq()
    username = username or f"student_{seq}_{uuid.uuid4().hex[:6]}"
    email = kwargs.pop("email", f"{username}@example.com")
    id_number = kwargs.pop("id_number", f"{100000000000000 + seq}")
    password = kwargs.pop("password", "TestPass123!")

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=User.Role.STUDENT,
        id_number=id_number,
        **kwargs,
    )
    if batch:
        BatchMembership.objects.create(
            user=user,
            batch=batch,
            status=BatchMembership.Status.APPROVED,
            is_cr=cr,
        )
    return user


def make_lecturer(username=None, **kwargs):
    seq = _seq()
    username = username or f"lecturer_{seq}_{uuid.uuid4().hex[:6]}"
    email = kwargs.pop("email", f"{username}@example.com")
    id_number = kwargs.pop("id_number", f"LEC-{seq:04d}")
    password = kwargs.pop("password", "TestPass123!")

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=User.Role.LECTURER,
        id_number=id_number,
        is_active=True,
        **kwargs,
    )
    return user


def sample_pdf_file(filename="test.pdf", content=b"%PDF-1.4 sample content\n%%EOF"):
    return SimpleUploadedFile(filename, content, content_type="application/pdf")


def make_note(owner=None, status=Note.Status.PENDING, **kwargs):
    if owner is None:
        owner = make_student()
    seq = _seq()
    department = kwargs.pop("department", None)
    batch = kwargs.pop("batch", None)
    if department is None:
        if hasattr(owner, "membership") and owner.membership and owner.membership.batch:
            department = owner.membership.batch.department
            batch = batch or owner.membership.batch
        else:
            department = make_department()
    title = kwargs.pop("title", f"Note Title {seq}")
    course_code = kwargs.pop("course_code", f"CSE{seq:03d}")
    semester = kwargs.pop("semester", 1)
    file_obj = kwargs.pop("file", sample_pdf_file())
    visibility = kwargs.pop("visibility", Note.Visibility.PUBLIC)

    note = Note.objects.create(
        owner=owner,
        title=title,
        course_code=course_code,
        department=department,
        batch=batch,
        semester=semester,
        file=file_obj,
        visibility=visibility,
        status=status,
        **kwargs,
    )
    return note


def give_credits(user, n, reason=CreditLedger.Reason.ADMIN, description="Test credits"):
    return add_entry(user, n, reason, description)
