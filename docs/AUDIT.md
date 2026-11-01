# Codebase Audit (Phase 0)

This document records the architectural baseline, models, URL mappings, settings, and implementation status of features in the **Gayn Kotor** codebase as required by Task 0.1 of `PRD.md`.

---

## 1. Installed Applications

Configured in `config/settings.py`:
- `django.contrib.admin`
- `django.contrib.auth`
- `django.contrib.contenttypes`
- `django.contrib.sessions`
- `django.contrib.messages`
- `django.contrib.staticfiles`
- `accounts`
- `core`
- `campus`
- `credits`
- `notes`
- `notifications`
- `courses`

---

## 2. Models and Fields: `accounts` & `campus`

### 2.1 `accounts` App

#### `accounts.models.User` (inherits `AbstractUser`)
- **Base Fields** (from `AbstractUser`): `username`, `first_name`, `last_name`, `password`, `is_staff`, `is_active`, `is_superuser`, `last_login`, `date_joined`, `groups`, `user_permissions`.
- **Custom Fields**:
  - `email`: `EmailField(_("email address"), unique=True)`
  - `role`: `CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)`
    - Roles: `student` ("Student"), `lecturer` ("Lecturer")
  - `id_number`: `CharField(_("ID number"), max_length=30, unique=True)`
  - `is_email_verified`: `BooleanField(default=False)`
- **Validation (`clean`)**:
  - Superuser: checks bypassed.
  - Student: requires 15 to 17 numeric digits (`r"\d{15,17}"`).
  - Lecturer: requires 3 to 30 characters of letters, digits, and hyphens (`r"[A-Za-z0-9-]{3,30}"`).
- **Signup Behavior (`accounts/forms.py`)**:
  - Lecturers are registered with `is_active = False` (requiring admin activation).
  - Students select a batch and create a `BatchMembership(status=PENDING)`.
  - Immediate signup bonus of 30 credits is granted via `credits.services.add_entry(user, 30, CreditLedger.Reason.SIGNUP_BONUS, "Welcome bonus")`.

---

### 2.2 `campus` App

#### `campus.models.Department`
- `name`: `CharField(_("name"), max_length=100, unique=True)`
- `code`: `CharField(_("code"), max_length=10, unique=True)`
- **Meta**: `ordering = ["name"]`

#### `campus.models.Batch`
- `department`: `ForeignKey(Department, on_delete=models.CASCADE, related_name="batches")`
- `name`: `CharField(_("batch"), max_length=50)`
- `class_teacher`: `ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="class_teacher_of", limit_choices_to={"role": "lecturer"})`
- **Meta**:
  - `ordering = ["department", "name"]`
  - `verbose_name_plural = "batches"`
  - `UniqueConstraint(fields=["department", "name"], name="unique_batch_per_department")`

#### `campus.models.BatchMembership`
- `user`: `OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membership")`
- `batch`: `ForeignKey(Batch, on_delete=models.CASCADE, related_name="memberships")`
- `status`: `CharField(max_length=10, choices=Status.choices, default=Status.PENDING)`
  - Statuses: `pending` ("Pending"), `approved` ("Approved"), `rejected` ("Rejected")
- `is_cr`: `BooleanField(default=False)`
- `created_at`: `DateTimeField(auto_now_add=True)`

---

## 3. URL Map

All route mappings configured across the project:

| Prefix / Path | App | View / Target | Name |
|---|---|---|---|
| `/admin/` | `admin` | `admin.site.urls` | N/A |
| **Accounts** (`/accounts/`) | `accounts` | | |
| `/accounts/signup/` | `accounts` | `accounts.views.signup` | `accounts:signup` |
| `/accounts/login/` | `accounts` | `auth_views.LoginView` (template: `accounts/login.html`) | `accounts:login` |
| `/accounts/logout/` | `accounts` | `auth_views.LogoutView` | `accounts:logout` |
| **Campus** (`/campus/`) | `campus` | | |
| `/campus/manage/` | `campus` | `campus.views.manage` | `campus:manage` |
| `/campus/membership/<int:pk>/` | `campus` | `campus.views.membership_action` | `campus:membership_action` |
| **Credits** (`/credits/`) | `credits` | | |
| `/credits/hollow/` | `credits` | `credits.views.hollow` | `credits:hollow` |
| **Notes** (`/notes/`) | `notes` | | |
| `/notes/` | `notes` | `notes.views.note_list` | `notes:list` |
| `/notes/upload/` | `notes` | `notes.views.upload` | `notes:upload` |
| `/notes/<int:pk>/preview/` | `notes` | `notes.views.note_preview` | `notes:preview` |
| `/notes/reviews/` | `notes` | `notes.views.review_list` | `notes:review_list` |
| `/notes/reviews/<int:pk>/` | `notes` | `notes.views.review_detail` | `notes:review_detail` |
| `/notes/reviews/<int:pk>/action/` | `notes` | `notes.views.review_action` | `notes:review_action` |
| `/notes/<int:pk>/file/` | `notes` | `notes.views.note_file` | `notes:file` |
| `/notes/<int:pk>/` | `notes` | `notes.views.note_detail` | `notes:detail` |
| `/notes/<int:pk>/download/` | `notes` | `notes.views.note_download` | `notes:download` |
| `/notes/<int:pk>/rate/` | `notes` | `notes.views.note_rate` | `notes:rate` |
| **Notifications** (`/notifications/`) | `notifications` | | |
| `/notifications/summary/` | `notifications` | `notifications.views.summary` | `notifications:summary` |
| `/notifications/<int:pk>/open/` | `notifications` | `notifications.views.open_notification` | `notifications:open` |
| `/notifications/read-all/` | `notifications` | `notifications.views.mark_all_read` | `notifications:read_all` |
| **Core** (`/`) | `core` | | |
| `/` | `core` | `core.views.home` | `core:home` |
| **Courses** (`/courses/`) | `courses` | | |
| `/courses/` | `courses` | `courses.views.course_list` | `courses:course_list` |
| `/courses/create/` | `courses` | `courses.views.create_course` | `courses:create_course` |

---

## 4. Current Settings Audit

### 4.1 Existing Settings (`config/settings.py`)
- `BASE_DIR`: Project root path.
- `SECRET_KEY`: Read from env `SECRET_KEY`.
- `DEBUG`: Read from env `DEBUG == "True"`.
- `ALLOWED_HOSTS`: `['localhost', '127.0.0.1', '.onrender.com']` + `RENDER_EXTERNAL_HOSTNAME` / `ALLOWED_HOSTS` env vars.
- `CSRF_TRUSTED_ORIGINS`: `['https://*.onrender.com']` + `RENDER_EXTERNAL_HOSTNAME` / `CSRF_TRUSTED_ORIGINS` env vars.
- `MIDDLEWARE`: Includes `SecurityMiddleware`, `WhiteNoiseMiddleware`, `SessionMiddleware`, `CommonMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`, `XFrameOptionsMiddleware`, `LocaleMiddleware`.
- `ROOT_URLCONF`: `'config.urls'`.
- `TEMPLATES`: DjangoTemplates with context processors `request`, `auth`, `messages`, `credits.context_processors.credit_balance`.
- `WSGI_APPLICATION`: `'config.wsgi.application'`.
- `DATABASES`: Neon Postgres config with fallback: unpooled connection (`DATABASE_URL_UNPOOLED`) for migrations, pooled (`DATABASE_URL`) for runtime app queries.
- `AUTH_PASSWORD_VALIDATORS`: Standard Django validators.
- `LANGUAGE_CODE`: `'en'` (languages: `'en'`, `'bn'`).
- `TIME_ZONE`: `'Asia/Dhaka'`.
- `USE_I18N`: `True`, `USE_TZ`: `True`.
- `STATIC_URL`: `'/static/'`, `STATICFILES_DIRS`: `[BASE_DIR / 'static']`, `STATIC_ROOT`: `BASE_DIR / 'staticfiles'`.
- `STORAGES`: Default FileSystemStorage, staticfiles CompressedStaticFilesStorage (WhiteNoise).
- `MAILERS`: Django console EmailBackend.
- `AUTH_USER_MODEL`: `'accounts.User'`.
- `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`: Configured to `'accounts:login'` and `'core:home'`.
- `MEDIA_ROOT`: `BASE_DIR / "media"`, `MEDIA_URL`: `"/media/"`.
- `NOTE_ESCALATE_DAYS`: `3` (defined at line 234).
- `NOTE_AUTOPUBLISH_DAYS`: `7` (defined at line 235).

### 4.2 Missing PRD Settings (To be added according to Section 3)
- `NOTE_CR_REMINDER_DAYS`: missing (Default: 2)
- `NOTE_MAX_UPLOAD_MB`: missing (Default: 20)
- `NOTE_REPORT_THRESHOLD`: missing (Default: 3)
- `NOTE_MAX_REWARDED_RATERS`: missing (Default: 10)
- `NOTE_UNVERIFIED_REWARD_DOWNLOADS`: missing (Default: 3)
- `ALLOWED_EMAIL_DOMAINS`: missing (Default: `""`)
- `SIGNUP_BONUS`: missing (Default: 30)
- `SITE_NAME`: missing (Default: `"Gayn Kotor"`)
- `CREDIT_PRICE_BDT`: missing (Default: 1)
- `CREDIT_TOPUP_MIN / MAX`: missing (Default: 10 / 5000)
- `PAYMENT_GATEWAY`: missing (Default: `"sandbox"`)
- `PRIVATE_MEDIA_ROOT`: missing (Default: `BASE_DIR / "private_media"`)

---

## 5. Status of Email Verification and Sign-up Bonus

### Email Verification: NOT Implemented
- The `accounts.models.User` model defines `is_email_verified = models.BooleanField(default=False)`.
- However:
  1. No verification tokens or timestamp signer logic exist.
  2. No verification routes or views exist (e.g., `/accounts/verify/<token>/`).
  3. No emails containing verification links are dispatched upon user registration.
  4. Users are able to log in and access features immediately without email verification.

### Sign-up Bonus: Implemented at Signup (Not Gated by Verification)
- In `accounts/forms.py` (lines 58-59), `add_entry(user, 30, CreditLedger.Reason.SIGNUP_BONUS, "Welcome bonus")` is executed synchronously during form save.
- Thus, every student and lecturer account receives 30 credits at account creation time, without email verification or idempotency checks against duplicate registration.

---

## 6. Definition of `NOTE_ESCALATE_DAYS` and `NOTE_AUTOPUBLISH_DAYS`

- Both settings are defined at the end of `config/settings.py`:
  - Line 234: `NOTE_ESCALATE_DAYS = 3`
  - Line 235: `NOTE_AUTOPUBLISH_DAYS = 7`
- They are consumed in:
  - `notes/models.py`:
    - `Note.is_overdue`: `timezone.now() - self.created_at >= timedelta(days=settings.NOTE_ESCALATE_DAYS)`
    - `Note.days_left_to_autopublish`: `self.created_at + timedelta(days=settings.NOTE_AUTOPUBLISH_DAYS) - timezone.now()`
  - `notes/services.py`:
    - `publish_overdue_notes`: `cutoff = timezone.now() - timedelta(days=settings.NOTE_AUTOPUBLISH_DAYS)`
