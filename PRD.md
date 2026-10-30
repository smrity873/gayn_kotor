# PRD.md: Campus Knowledge and Skill Exchange (Skillo / Gayn Kotor)

Remaining-work PRD, written to be executed phase by phase with the `agy` CLI.
Stack: Python, Django 6.1, PostgreSQL, HTML, Tailwind CSS (CDN), raw JavaScript.

---

## 0. How to run this PRD with agy

I have not assumed any `agy` flags. Run `agy --help` to see how it takes a prompt (interactive or one-shot) and paste the prompt blocks below in whatever form it accepts.

Rules for every session:

1. One phase per session. Never start the next phase on your own.
2. Start every session by reading: this file's sections 2 and 3, the phase section, and every file the phase lists under "Read first".
3. Work on a branch named `phase-N-short-name`. Commit after each numbered task.
4. Finish with the verification commands in section 9. If anything fails, fix it before reporting.
5. Stop and ask (do not guess) when: a new dependency is needed, a migration would delete data, an Open Decision (section 8) has no default, or the code contradicts this PRD.
6. End with a report: files changed, migrations added, tests added, deviations from this PRD, open questions.

**Reusable prompt (replace N and NAME):**

```
Read PRD.md sections 2, 3 and "Phase N: NAME". Open every file listed under
"Read first" before writing code. Create branch phase-N-NAME. Implement the
tasks in order, one commit per task, following the global rules in section 2.
Run the verification commands. Do not touch anything outside the phase scope.
Finish with the report described in section 0 and stop.
```

---

## 1. Product snapshot

Three pillars on one internal currency ("nuts" in the UI, "credits" in code):
notes (paid in credits), skill swap (paid in credits), video courses (paid in money).
Roles: admin (developer, emergencies only), lecturer, student. A student may also be a CR; a lecturer may be a class teacher of a batch.

### 1.1 Current state (from the uploaded code)

| Area | Status | Notes |
|---|---|---|
| Notes upload, preview (PyMuPDF), search, pagination, visibility (public/department/batch) | Done | |
| Review workflow: approve/reject with reason, lecturer auto-publish, 7-day auto-publish as "unverified" | Done | Reminder, escalation and concurrency guard missing |
| Note download (-5), rating (+5 owner, +1 rater), daily caps | Done | No per-file rater limit, no unverified-reward release |
| Credit ledger, `add_entry`, balance, context processor, read-only admin | Done | No reversal, no balance lock inside `add_entry` |
| Notifications model, polling bell (30 s), open, read-all | Done | Many events never fire (see Phase 2) |
| Campus: batch join requests, approve/reject, make/remove CR | Done | No suspend/disable |
| Nut Hollow page | Partial | Uses a looping `video.mp4` plus a counter; does not react to credit changes |
| Accounts: signup, login, logout | Partial | Email verification and the 30-credit gating are unconfirmed; password reset missing; signup "Log in" link is `href="#"` |
| Reports, appeals, teacher note removal | Missing | `REMOVED` status exists but no flow |
| Payments (sandbox gateway, credit purchase) | Missing | No `payments` app |
| Skill swap | Missing | Only a stub `SkillSwap` model inside `courses` |
| Video courses | Stub | Single `video_file` per course, no pricing rules, no purchase flow, no streaming, "View Course" is `#` |
| Role dashboards, home page dynamic sections | Missing | Home is static |
| Tests | Missing | Every `tests.py` is empty |
| Docs (proposal, README, ERD) | Missing | |

### 1.2 Files the agent has not been shown

The upload did not include `config/settings.py`, `config/urls.py`, `accounts/*`, `campus/*`, or `templates/campus` beyond `manage.html`. Phase 0 must read them and record what exists in `docs/AUDIT.md` before anything is built on assumptions.

---

## 2. Global engineering rules

**Credits**
- Balances are never stored or edited. Every change is a `CreditLedger` row written through `credits.services.add_entry`.
- Any debit must run inside `transaction.atomic()` with the user row locked (`select_for_update`). Phase 0 moves that lock inside `add_entry`.
- Ledger rows are append-only. Corrections are new rows (reversal), never edits or deletes.
- Every rule number (rewards, costs, caps, days, percentages) lives in `settings.py`, overridable by env, never hard-coded in views.

**Money (BDT)**
- Use `Decimal` only. Never `float`.
- Wallet balance is also a sum of ledger rows (Phase 7), never a stored field that is edited.
- Payment fulfilment must be idempotent: calling it twice never pays twice.

**Security**
- Every view is `@login_required` unless it is a public page. Every object view checks permission at object level (not only by role).
- Every state-changing action is POST with CSRF.
- Paid or private files (note PDFs, videos) are never served from a guessable public URL. They are served by a permission-checked view.
- No user input is trusted for price, credits, role or status. Compute server-side.
- Failure of an email or notification must never roll back a credit or payment action.

**Files**
- Files and media should store in object storage (firebase free s3 storage or other free tier), never store in static project folders most of the server refuse this.

**Code style (match what exists)**
- Business logic in `services.py`; views stay thin.
- Templates extend `base.html`, use the existing Tailwind classes (`green-*`, `bg-card`, `dark:bg-card-dark`, `nut`, rounded-2xl cards, rounded-full buttons) and always include dark-mode classes.
- Forms reuse `accounts.forms.INPUT_CLASSES`.
- Every new page: empty state, error state, mobile layout, dark mode.
- Notifications go through `notifications.services.notify / notify_many`.

**Tests**
- Each phase adds tests for its own rules. Use `django.test.TestCase`.
- Minimum per phase: happy path, permission denial, double-submit/idempotency, and every edge case listed in the phase.
- `python manage.py test` must be green at the end of every phase.

**Migrations**
- One migration set per logical change. Never edit an applied migration. Data migrations are reversible where practical.

---

## 3. Settings and constants

Add to `config/settings.py`, reading env with `python-dotenv` defaults. Items marked (exists) are already referenced in code.

| Setting | Default | Phase |
|---|---|---|
| `NOTE_ESCALATE_DAYS` (exists) | 3 | 2 |
| `NOTE_AUTOPUBLISH_DAYS` (exists) | 7 | 2 |
| `NOTE_CR_REMINDER_DAYS` | 2 | 2 |
| `NOTE_MAX_UPLOAD_MB` | 20 | 0 |
| `NOTE_REPORT_THRESHOLD` | 3 | 2 |
| `NOTE_MAX_REWARDED_RATERS` | 10 | 2 |
| `NOTE_UNVERIFIED_REWARD_DOWNLOADS` | 3 | 2 |
| `ALLOWED_EMAIL_DOMAINS` | empty (any) | 1 |
| `SIGNUP_BONUS` | 30 | 1 |
| `SITE_NAME` | "Gayn Kotor" | 0 |
| `CREDIT_PRICE_BDT` | 1 | 3 |
| `CREDIT_TOPUP_MIN / MAX` | 10 / 5000 | 3 |
| `PAYMENT_GATEWAY` | `sandbox` | 3 |
| `SWAP_DEPOSIT` | 10 | 5 |
| `SWAP_FREE_CANCEL_HOURS` | 24 | 5 |
| `SWAP_DISPUTE_HOURS` | 24 | 5 |
| `SWAP_AUTO_RESOLVE_HOURS` | 72 | 5 |
| `SWAP_DEFAULT_DURATION_MIN` | 60 | 5 |
| `SWAP_ALLOWED_LINK_DOMAINS` | `meet.google.com, zoom.us, teams.microsoft.com` | 5 |
| `ENABLE_VIDEO_COURSES` | True | 7 |
| `COURSE_COMMISSION_PERCENT` | 10 | 7 |
| `COURSE_VIDEO_MAX_MB` | 300 | 7 |
| `COURSE_MIN_BILLABLE_HOURS` | 0.5 | 7 |
| `WITHDRAW_MIN_BDT` | 500 | 7 |
| `PRIVATE_MEDIA_ROOT` | `<BASE>/private_media` | 0 |

---

## 4. Phase overview

| Phase | Name | Size | Depends on |
|---|---|---|---|
| 0 | Baseline audit and hardening | M | none |
| 1 | Accounts: verification, bonus, safety | M | 0 |
| 2 | Notes completion and notifications | L | 0, 1 |
| 3 | Payments app (sandbox) and credit purchase | M | 0 |
| 4 | Nut Hollow animation and ledger admin | M | 0, 3 |
| 5 | Skill swap | L | 0, 3 |
| 6 | Dashboards, home page, navigation | M | 2, 5 |
| 7 | Video courses, wallet, withdrawals | L | 0, 3, 6 |
| 8 | Hardening, QA, documentation | M | all |

Phases 3 and 4 may swap order with 2 if needed. Phase 7 is the riskiest and the only pillar designed to be removable (`ENABLE_VIDEO_COURSES`).

---

## Phase 0: Baseline audit and hardening

**Goal:** know exactly what exists, close security gaps, and put a test net under the finished features.

**Read first:** `config/settings.py`, `config/urls.py`, `accounts/models.py`, `accounts/forms.py`, `accounts/views.py`, `accounts/urls.py`, `campus/models.py`, `campus/views.py`, `campus/urls.py`, `credits/services.py`, `notes/*`, `requirements.txt`.

**Tasks**

0.1 **Audit.** Write `docs/AUDIT.md`: models and fields of `accounts` and `campus`, URL map, installed apps, settings that exist, whether email verification and signup bonus are implemented, where `NOTE_ESCALATE_DAYS` / `NOTE_AUTOPUBLISH_DAYS` are defined. No behaviour changes in this task.

0.2 **Health.** Run `check`, `makemigrations --check --dry-run`, `showmigrations`. Fix drift only if it exists. Ensure `config/settings.py` defines every setting already referenced by code.

0.3 **Private file storage.** Note PDFs currently sit in `media/notes/YYYY/MM/<original name>`. If `MEDIA_URL` is served in dev, anyone who guesses a path bypasses the 5-credit unlock.
- Add `PRIVATE_MEDIA_ROOT` and a `FileSystemStorage(location=PRIVATE_MEDIA_ROOT)` with no public base URL (`private_storage` in `core/storage.py`).
- Point `Note.file` and `Note.preview` at it. Use a UUID-based `upload_to` so names are not guessable.
- Add a management command `move_private_files` that moves existing files and updates DB paths (dry-run flag).
- Confirm `config/urls.py` does not expose `PRIVATE_MEDIA_ROOT`. Public `MEDIA` may remain only for course thumbnails.

0.4 **Known defects.**
- `validate_file_size` allows 50 MB but the form says 20 MB. Use `NOTE_MAX_UPLOAD_MB` in both.
- Validate the PDF header (`%PDF-`) on upload, not only the extension.
- `notes/models.py` calls `get_user_model()` at import time. Replace with `settings.AUTH_USER_MODEL` strings.
- `note_file` must return 404 for `REMOVED` notes except to owner, reviewers and superuser.
- `templates/accounts/signup.html` "Log in" link: use `{% url 'accounts:login' %}`.
- `credits.services.add_entry`: lock the user row (`select_for_update`) inside the function whenever `amount < 0`, and add an `allow_negative=False` parameter (used later by reversals).
- `review_action`: re-fetch the note with `select_for_update` and require it is still reviewable; if another reviewer already decided, show "already decided" and change nothing ("whoever decides first is final").
- Add DB index on `CreditLedger(user, created_at)` and `Note(status, created_at)`.

0.5 **Brand constant.** Add `SITE_NAME` and a context processor; replace hard-coded "Gayn Kotor" in templates. Docs use "Skillo" only if Open Decision 1 says so.

0.6 **Test scaffold.** Create `core/testing.py` with factories: `make_department`, `make_batch(department, class_teacher=None)`, `make_student(batch, cr=False)`, `make_lecturer`, `make_note(owner, status=...)`, `give_credits(user, n)`.
Write tests for existing behaviour: `add_entry` (insufficient funds, atomicity), upload then approve pays reward exactly once, lecturer note auto-publishes, download deducts once and is idempotent, rating rules (own file, before download, twice, daily cap), visibility matrix (public / department / batch / lecturer), `publish_overdue_notes`, notification endpoints (ownership, open redirect safety).

**Acceptance**
- `docs/AUDIT.md` exists and matches reality.
- A guessed path under media cannot download a note PDF.
- Concurrent double-approve test: second approval is rejected, reward paid once.
- `python manage.py check`, `makemigrations --check`, `test` all pass.

---

## Phase 1: Accounts, verification, bonus, safety

**Goal:** the sign-up bonus is earned only by verified people, and bad accounts can be stopped without the admin.

**Read first:** Phase 0 `docs/AUDIT.md`, `accounts/*`, `campus/models.py`, `templates/accounts/*`, `templates/campus/manage.html`, `credits/services.py`.

**Tasks**

1.1 **Email verification.** Add `User.email_verified_at` (nullable). Signed token with `django.core.signing.TimestampSigner` (no new table), link `/accounts/verify/<token>/`, 3-day expiry. "Resend" view throttled to 1 per minute per user (cache). Console email backend in dev (`EMAIL_BACKEND` from env). Skip this task only if the audit proves it already exists; then just add tests.

1.2 **Bonus on verification, once.** Remove any bonus granted at signup. Grant `SIGNUP_BONUS` in one atomic function `grant_signup_bonus(user)` on first successful verification; guard with an existence check on `CreditLedger(reason=SIGNUP_BONUS)` under a user row lock. Notify the user.

1.3 **Verified gate.** Add `verified_required` decorator. Unverified users can log in, see a banner with a resend link, and are blocked from: uploading, unlocking notes, rating, requesting/booking swaps, buying/selling courses. Browsing remains allowed.

1.4 **Domain rule.** `ALLOWED_EMAIL_DOMAINS`: when non-empty, signup rejects other domains. When empty, the ID check by CR/class teacher is the safeguard (Open Decision 2).

1.5 **ID rules.** `id_number` required for students and lecturers, unique per role/department scope (confirm in audit; add a unique constraint only if safe).

1.6 **Suspension.** Class teacher can suspend and reactivate students of their batch; CRs can suspend students only of their own batch, never other CRs or the teacher; only admin touches lecturers. Fields: `suspended_at`, `suspended_by`, `suspension_reason` and `is_active=False` while suspended. Reason is required. Add buttons on `manage.html`, notify the user. A suspended user cannot log in and sees a clear message.

1.7 **Password and profile.** Password reset (Django auth views, themed templates), change password, read-only profile page showing role, ID, department, batch, verification status. Link from the profile popup in the navbar.

1.8 **Login throttle.** Cache-based: 5 failed attempts per username+IP per 15 minutes, generic error message.

**Acceptance**
- Signup gives 0 credits; verification gives exactly 30; clicking the link twice gives 30 total.
- Expired or tampered token is rejected.
- A CR cannot suspend another CR, the teacher, or a student of a different batch (test each).
- All new templates work in dark mode and on mobile.

---

## Phase 2: Notes completion and notifications

**Goal:** the full review lifecycle from the plan, with no scheduler required and every notification the plan lists.

**Read first:** `notes/models.py`, `notes/services.py`, `notes/views.py`, `notes/management/commands/publish_overdue.py`, `notifications/*`, `templates/notes/*`, `credits/services.py`, `campus/models.py`.

**Tasks**

2.1 **Fields and statuses.** Add to `Note`: `cr_reminded_at`, `escalated_at`, `last_reminder_at`, `status_before_flag` (nullable). Add `Status.FLAGGED`. Add `CreditLedger.Reason.REVERSAL`. One migration per app.

2.2 **Deadline engine** `process_review_deadlines(now=None)` in `notes/services.py`, idempotent:
- Day `NOTE_CR_REMINDER_DAYS` (2): notify batch CRs once (`cr_reminded_at`).
- Day `NOTE_ESCALATE_DAYS` (3): notify the class teacher once, set `escalated_at`; then one reminder per day (`last_reminder_at`).
- Day `NOTE_AUTOPUBLISH_DAYS` (7): publish as `UNVERIFIED` (existing function) and notify the uploader.
- Edge cases from the plan: batch with no CR goes straight to the class teacher; uploader is a CR means notify other CRs plus teacher, never the uploader; several CRs means first decision wins (Phase 0 guard); batch with neither CR nor teacher means no notification, auto-publish still applies.

2.3 **Command and lazy trigger.** Management command `send_reminders` runs the engine plus `publish_overdue_notes`, with `--dry-run` and `--now <ISO datetime>` for demos. Also call the engine from `review_list` and `note_list`, throttled by a cache key (every 5 minutes).

2.4 **Review UI.** Queue sorted escalated first, then oldest. Badges: "Escalated", "Auto-publishes in N days". Teacher sees all of their batches; CR sees only their batch.

2.5 **Appeals.** `NoteAppeal(note, user, message<=500, status open/upheld/granted, decided_by, decision_note, created_at, decided_at)`. Only the owner of a `REJECTED` note, one open appeal per note. Goes to the class teacher only (not CRs). Page `/notes/appeals/`. Granting calls `approve_note`; upholding requires a reason. Notify both sides.

2.6 **Reports and flagging.** `NoteReport(note, user, reason choice, details, created_at)` unique per user+note; owner cannot report own note; user must be able to view the note. At `NOTE_REPORT_THRESHOLD` distinct reporters: save `status_before_flag`, set `FLAGGED`, hide from lists, notify the class teacher. Page `/notes/flagged/`: dismiss (restore previous status, mark reports resolved) or remove. Users who already unlocked a flagged note keep access until it is removed.

2.7 **Teacher removal.** `remove_note(note, by, reason, reverse_reward=False)`: sets `REMOVED`, notifies the owner, and if `reverse_reward` and the reward was paid, writes a `REVERSAL` ledger row with `allow_negative=True`. Available from the note detail page to a class teacher of the note's batch (and superuser).

2.8 **Reward rules.**
- Owner's +5 only for the first `NOTE_MAX_REWARDED_RATERS` ratings of that file (add `NoteRating.owner_rewarded`).
- Unverified notes release the +10 upload reward after `NOTE_UNVERIFIED_REWARD_DOWNLOADS` unlocks, still guarded by `reward_paid`.

2.9 **Notification gaps.** Add: rating received (message includes stars and nuts), credits added or deducted (via `add_entry(..., notify=True)` using `transaction.on_commit`; callers that send a richer message pass `notify=False`), note flagged, appeal events, removal. Add optional `email=True` on `notify()` using `send_mail(fail_silently=True)`. Add a full notifications page `/notifications/` with pagination (the bell only shows 8).

**Acceptance (all tested with a controllable `now`)**
- A note at day 1, 2, 3, 4, 7 produces exactly the expected notifications; running the engine twice produces no duplicates.
- Appeal by a non-owner is denied; second open appeal is blocked.
- Three reports hide the note; dismiss restores the exact previous status.
- 11th rater earns the owner nothing; the rater still gets their own reward subject to the daily cap.
- A removed note's PDF returns 404 to a user who had unlocked it.

---

## Phase 3: Payments app (sandbox) and credit purchase

**Goal:** a gateway abstraction with a working sandbox, used first to buy credits and later to buy courses.

**Read first:** `credits/*`, `courses/models.py`, `notifications/services.py`, `templates/notes/note_detail.html`, `templates/credits/hollow.html`.

The plan mentions earlier payment and wallet code from "the first version". It is not in the uploaded files, so write this fresh unless the owner drops that code into the repo (Open Decision 9).

**Tasks**

3.1 **App `payments`.** Add to `INSTALLED_APPS`.
`PaymentOrder`: `id` (UUID), `user`, `purpose` (`credit_topup` / `course`), `amount_bdt` (Decimal), `reference_type`, `reference_id` (plain fields, no cross-app FKs), `status` (created, pending, paid, failed, cancelled), `gateway`, `gateway_txn_id` (unique, nullable), `created_at`, `paid_at`.

3.2 **Gateway interface.** `payments/gateways/base.py`:
```python
class PaymentGateway:
    name: str
    def create_payment(self, order, return_url) -> str: ...   # URL to send the user to
    def parse_callback(self, request) -> "PaymentResult": ... # order id, success flag, txn id
```
`sandbox.py`: redirects to `/payments/sandbox/<order_id>/`, a page with "Pay" and "Fail" POST buttons that go through the same `complete_order()` path a real gateway callback would use. Select the gateway by `PAYMENT_GATEWAY`. The sandbox page must refuse to work when `DEBUG=False` unless `SANDBOX_ALLOWED=True`.

3.3 **Fulfilment registry.** `fulfil_order(order)`: atomic, `select_for_update` on the order, no-op if already paid, then call the function registered for `order.purpose` (`register_fulfiller("credit_topup", fn)`). `payments` must not import `credits` or `courses` directly; those apps register themselves in `AppConfig.ready()`.

3.4 **Credit top-up.** Credits are computed server-side: `credits = amount_bdt / CREDIT_PRICE_BDT`, integer only, within `CREDIT_TOPUP_MIN..MAX`. Fulfiller writes `PURCHASE` ledger rows and notifies the user. Credits can never be withdrawn as money (no such code path).

3.5 **UI.** `/payments/credits/buy/` with preset packs (50 / 100 / 200) and a custom amount; order history at `/payments/orders/`. Add "Buy nuts" to the hollow page and to the "not enough nuts" box in `note_detail.html`.

**Acceptance**
- Pay then replay callback: credits added once.
- Fail or cancel: no credits.
- Tampering with a posted credit count or amount has no effect.
- Amount below min or above max is rejected.
- An order of another user cannot be viewed or completed.

---

## Phase 4: Nut Hollow animation and ledger admin

**Goal:** the hollow reacts to the user's credit changes, as the plan describes, and the admin can inspect and reverse ledger entries.

**Read first:** `templates/credits/hollow.html`, `credits/*`, `static/images/video.mp4` (do not delete it).

**Tasks**

4.1 **State endpoint.** `GET /credits/hollow/state/` returns JSON: exact `balance`, and the last 20 ledger entries with `id`, `amount`, `reason`, `created_at`.

4.2 **Scene.** Replace the looping video with an inline SVG scene (tree, hollow, squirrel) styled with CSS keyframes and raw JavaScript. Keep `video.mp4` in `static/` untouched for rollback (Open Decision 10).
- Draw `min(balance, 30)` nuts in or around the hollow; show the exact number in a counter.
- On load, compare the newest ledger id with `localStorage["hollow_last_seen"]`. For each newer entry: positive means the squirrel carries nuts in; negative means nuts are taken out; `PURCHASE` plays a happy bounce. Cap animated nuts per event at 10 and queue events so they play one after another.
- Respect `prefers-reduced-motion` (skip to final state). Keep the "Replay" button.
- Wrap localStorage access in try/catch.

4.3 **Full ledger page.** `/credits/ledger/` paginated, filter by reason, same row design as the hollow page.

4.4 **Admin ledger tools.** In `credits/admin.py`: action "Reverse selected entries" creating a `REVERSAL` row (`allow_negative=True`) with description `Reversal of #<id>`. Add `CreditLedger.reverses` (nullable OneToOne to self) so one entry can only be reversed once. Add filters by date and user.

4.5 **Integrity command.** `check_ledger`: lists users with negative balance, duplicate signup bonuses, duplicate upload rewards for one note, and reversals without a target. Read-only.

**Acceptance**
- Earning, spending and buying each trigger the right animation; refreshing does not replay already-seen entries.
- Balance of 500 shows 30 nuts and the number 500.
- Reversing the same entry twice is blocked.
- Page is usable on a 360 px screen and with reduced motion.

---

## Phase 5: Skill swap (`swaps` app)

**Goal:** peer teaching sessions with deposits, safe meeting links, and fair outcomes when someone does not show.

**Read first:** `courses/models.py` (stub `SkillSwap`), `credits/*`, `notifications/*`, `campus/models.py`, `templates/partials/navbar.html`.

**Tasks**

5.1 **App and cleanup.** Create `swaps`. Remove the stub `SkillSwap` model and admin from `courses` with a migration. It holds no real data; if the audit shows rows, stop and ask.

5.2 **Models.**
- `SkillPost(user, kind offer|request, skill_name, normalized_skill, description, is_active, created_at)`. `normalized_skill` is lowercase, trimmed, whitespace-collapsed, set in `save()`.
- `SwapSession(teacher, learner, post nullable, skill_name, status, proposed_time nullable, meeting_link blank, deposit_held bool, teacher_outcome, learner_outcome, teacher_outcome_at, learner_outcome_at, created_at, updated_at)`.
- `SessionRating(session, rater, rating 1-5, comment, created_at)` unique per session and rater. Ratings give no credits.

5.3 **State machine.**

| From | Action | To | Who |
|---|---|---|---|
| none | request | `requested` | learner (cannot be the teacher) |
| `requested` | accept and propose time | `accepted` | teacher |
| `requested` | decline | `declined` | teacher |
| `accepted` | confirm time | `scheduled`, deposits held | learner |
| `accepted` | propose new time | `accepted` | either |
| `scheduled` | cancel | `cancelled` (see 5.4) | either |
| `scheduled` | report outcome after start time | `completed`, `no_show` or `disputed` (5.4) | each side |
| `requested` / `accepted` | no response in 7 days | `expired` | system |

One open request per learner per post. Both users must be email-verified.

5.4 **Deposit rules** (`SWAP_DEPOSIT` from each side; ledger reasons already exist):
- On `scheduled`: lock both users in ascending id order, require both balances at least the deposit, write two `SWAP_HOLD` rows (negative). All or nothing. If someone is short, show a link to buy credits.
- Both report "completed": two `SWAP_RETURN` rows (+deposit each).
- One side reports the other as no-show and the other does not contest within `SWAP_DISPUTE_HOURS`: the no-show side loses the held deposit. The attending side gets `SWAP_RETURN` (+deposit) and `SWAP_FORFEIT` (+deposit). Credits are conserved.
- Reports contradict (one says "completed", the other says "no-show"): status `disputed`, both deposits returned, both notified. The admin only adjusts by ledger reversal in emergencies.
- Nobody reports within `SWAP_AUTO_RESOLVE_HOURS` after the start time: both deposits returned.
- Cancel at least `SWAP_FREE_CANCEL_HOURS` before start: both returned. Later cancel: treated as a no-show by the canceller.
- All transitions idempotent and wrapped in one `transaction.atomic()`.

5.5 **Meeting link.** Only the teacher sets or edits it (until `completed`). Validator: scheme `https`, hostname equals or is a subdomain of an allowed domain, no username/password in the URL, length at most 300. Visible only to the two participants and superusers, enforced in the view and template. Never put the URL in a notification text; say "link added" and link to the session page.

5.6 **Browse and match.** `/swaps/` with tabs Offers, Requests, My sessions. A "Matches for you" panel: other people whose offers equal my requests (by `normalized_skill`), highlighted as a mutual swap when my offers equal theirs too. A mutual swap is simply two separately booked sessions.

5.7 **Engine.** Command `resolve_swaps` applies every time-based rule above (expiry, auto-resolve, dispute window) and runs lazily on session page load. It must be idempotent.

5.8 **Notifications.** Session requested, accepted, time confirmed or changed, link added, cancelled, outcome reported, deposit returned or forfeited, rating received.

5.9 **UI.** Pages for list, post create/edit/deactivate, session detail with a status timeline and the correct action buttons per role and state, rating form after completion. Replace the "#" links for Skill Swap in the navbar.

**Acceptance**
- Concurrent attempts to confirm one session hold deposits only once.
- Sum of ledger amounts across both users is unchanged after every resolution path except the intended transfer in the no-show case.
- A third user cannot read the link, the session page, or rate the session.
- A link to `evil.com`, `http://meet.google.com`, `https://meet.google.com.evil.com`, and `https://user@zoom.us` are all rejected; `https://us02web.zoom.us/j/123` is accepted.

---

## Phase 6: Dashboards, home page, navigation

**Goal:** each role lands on a useful dashboard, and the home page shows real content.

**Read first:** `core/*`, `templates/home.html`, `templates/partials/navbar.html`, `notes/services.py`, `swaps/*`.

**Tasks**

6.1 **`/dashboard/`** in `core`, redirecting by role (logic in `core/dashboard.py`, one context-builder per role):
- **Student:** nut balance, recent ledger, unlocked notes, my notes by status, upcoming sessions, unread notifications. CR users also get a review-queue summary.
- **Class teacher (lecturer):** escalated notes, flagged notes, open appeals, pending join requests, member count, CR list, links to Manage Batch.
- **Lecturer:** own notes with unlock counts, own sessions, courses and earnings once Phase 7 lands (hide the course widgets behind `ENABLE_VIDEO_COURSES`).
- **Admin:** link to `/admin/`, counts, `check_ledger` summary. The admin dashboard performs no moderation.
- A user with several roles (CR, class teacher) sees the union of widgets.

6.2 **Home page.** Popular notes (top 6 by unlocks, public and published only, so nothing private leaks to anonymous visitors), latest published courses (flag-gated), platform counters. Logged-in visitors get a "Go to dashboard" button instead of "Get started".

6.3 **Navigation.** Add Dashboard to the navbar and mobile menu. Replace placeholder `#` links for Courses and Skill Swap. Keep the profile popup actions consistent with role.

6.4 **Polish.** Themed 403, 404 and 500 templates. Consistent empty states. Footer links.

**Acceptance**
- Each role sees only its widgets; anonymous visitors never see non-public note data.
- Dashboard issues a bounded number of queries (assert with `assertNumQueries` ranges, no N+1).

---

## Phase 7: Video courses, wallet, withdrawals

**Goal:** the money pillar, safe to switch off. Build last.

**Read first:** `courses/*`, `templates/courses/*`, `payments/*`, `credits/models.py` (for the ledger pattern), `config/settings.py`.

Before starting, confirm with the teacher that a money-based pillar is acceptable (Open Decision 5). The whole pillar sits behind `ENABLE_VIDEO_COURSES`: URLs, nav links, home sections and dashboard widgets all disappear when it is false.

**Tasks**

7.1 **Restructure models.**
- `Course(instructor, title, description, category academic|non_academic, price Decimal, thumbnail, status draft|published, total_duration_seconds, created_at, updated_at)`.
- `Lesson(course, title, order, video_file, duration_seconds, is_free_preview)`, stored in private storage with UUID filenames.
- Data migration: for each existing `Course.video_file`, create one `Lesson`; then remove the field. Remove `InstructorWallet` and the leftover `SkillSwap` from `courses`.
- `CoursePurchase` keeps its fields and gains `commission_amount`, `seller_earning`, and a unique constraint on (`user`, `course`) where `is_successful`.
- Courses videos should store on s3 object storage, and taking link of youtube playlist/solo video as unlisted privacy.

7.2 **Pricing rules.** `PricingRule(category unique, min_per_hour, max_per_hour)` editable in admin, seeded with placeholder values (Open Decision 7).
`billable_hours = max(total_duration_seconds / 3600, COURSE_MIN_BILLABLE_HOURS)`. Allowed price is `[min_per_hour * billable_hours, max_per_hour * billable_hours]`. Validation happens in the form and again on publish. If lessons change after publishing and the price falls outside the range, the course is automatically moved back to draft and the seller is notified. YouTube's courses price would cheap but for s3 storages course would high. there would have filter system also for free/premium courses.

7.3 **Upload and duration.** MP4 only, per-file and per-course size limits from settings. Read duration server-side with `mutagen` (pure Python; this is a new dependency, so pin it in `requirements.txt` and mention it in the report). Reject files whose duration cannot be read. Client-side duration from `loadedmetadata` is only a live hint on the form; the server value is the one that counts.

7.4 **Who can sell.** Helper `can_sell(user)`: verified email, plus either a lecturer or a student with an approved batch membership. A seller cannot buy their own course.

7.5 **Catalog and management.**
- List with search, category filter, price sort and pagination; fix the "View Course" link.
- Detail page: description, lesson list with durations, seller, price, buy button or "Owned".
- Seller pages: my courses, add / reorder / delete lessons, publish toggle, earnings summary.

7.6 **Purchase flow.** Create a `PaymentOrder(purpose="course")` with the price read at order time. The `courses` app registers a fulfiller that creates the `CoursePurchase`, splits commission (`COURSE_COMMISSION_PERCENT`), credits the seller's wallet, and notifies the seller. Fulfilment is idempotent; a second purchase of the same course is blocked.

7.7 **Wallet ledger.** In `payments`: `Wallet(user)` is optional metadata only; the balance is the sum of `WalletEntry(user, amount Decimal signed, reason course_sale|withdrawal_hold|withdrawal_reversal|adjustment, reference, created_at)`. Entries are append-only. Add a `get_wallet_balance(user)` service.

7.8 **Withdrawals.** `WithdrawalRequest(user, amount, method, account_details, status pending|paid|rejected, admin_note, created_at, decided_at)`. Minimum `WITHDRAW_MIN_BDT`, cannot exceed balance. Creating a request writes a negative `withdrawal_hold` entry atomically; rejecting writes a `withdrawal_reversal`; marking paid changes status only. Handled by admin actions (manual process, as the plan states). Seller sees status.

7.9 **Secure streaming.**
- `/courses/lesson/<id>/stream/` allows the buyer, the seller, superusers, or anyone when `is_free_preview`.
- Must support HTTP Range (206, `Content-Range`, `Accept-Ranges: bytes`) with chunked reads, because Django's `FileResponse` does not do this for you. Add a `Cache-Control: private` header. Allow an optional `X-Accel-Redirect` mode for nginx via a setting.
- Learn page `/courses/<id>/learn/` uses an HTML5 player with `controlsList="nodownload"`. This is only a deterrent, and the docs must say so honestly.
- No raw media URL for videos exists anywhere.

**Acceptance**
- A non-buyer cannot stream a lesson (403/404) and cannot discover a direct file URL.
- Seeking in the player works (Range tests: `bytes=0-99`, `bytes=100-`, invalid range gives 416).
- Price outside the range cannot be saved or published; boundary values (exactly min and exactly max) are accepted.
- Commission math: price 1000 at 10% gives seller 900, platform 100; running fulfilment twice credits once.
- Withdrawal above balance, below minimum, or concurrent double-request is rejected.
- With `ENABLE_VIDEO_COURSES=False` no course link, page or home section is reachable.

---

## Phase 8: Hardening, QA, documentation

**Goal:** a demo-ready, defensible final system plus the documents the department asks for.

**Tasks**

8.1 **Security pass.** Run `python manage.py check --deploy` and fix findings. Production settings from env: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, secure cookies, HSTS. Write an object-level permission test matrix covering every id-based URL (IDOR): note, preview, file, review, appeal, flagged, session, lesson stream, order, withdrawal.

8.2 **Performance.** `select_related` / `prefetch_related` review of every list page; the `credit_balance` context processor runs an aggregate on every request, so cache it per request (and invalidate on write). Confirm indexes exist for the common filters.

8.3 **Demo data.** Management command `seed_demo`: departments, batches, class teachers, CRs, students, lecturers, notes of different ages (so `send_reminders --now` demonstrates escalation), sessions in each state, courses, and a sandbox payment. Idempotent and refuses to run when `DEBUG=False`.

8.4 **Full scenario tests.** End to end: signup, verify, bonus, upload, escalate, approve, unlock, rate, report, flag, remove; swap booking to completion and no-show; credit purchase; course purchase, stream, withdrawal.

8.5 **UX pass.** 360 px, 768 px and desktop widths; dark mode everywhere; keyboard focus; text rendering with the existing font stack.

8.6 **Documents.**
- `README.md`: setup, `.env` keys (update `.env.example`), commands, cron lines for `send_reminders` and `resolve_swaps`, how to demo escalation.
- `docs/ARCHITECTURE.md`: apps, request flow, credit and wallet ledgers, Mermaid diagrams.
- `docs/ERD.md`: ER diagram from the real models (Mermaid).
- `Project_Proposal.md`: fill every section 1 to 17 of `BSc_Computer_Engineering_Project_Proposal_Format.md` using this project; leave student and supervisor fields blank; the timeline table reflects the actual phases.
- `Improvements.md`: future work (real payment gateway, cloud video storage with signed URLs, scheduler/Celery, push notifications, refund policy, content moderation for courses, mutual-swap bundles, mobile app).
- Deployment notes: gunicorn and nginx, PostgreSQL backups, private media location.

**Acceptance**
- Fresh clone to running demo using only the README.
- `makemigrations --check`, `check --deploy`, and `test` all clean.
- Proposal follows the department format section by section.

---

## Misselenious
- If s3 storage did not work, use tha database as file storage with binary conversion using multer

## 5. Data model additions (summary)

| App | New or changed |
|---|---|
| accounts | `User.email_verified_at`, `suspended_at/by/reason` |
| credits | `Reason.REVERSAL`, `CreditLedger.reverses`, indexes |
| notes | `Note` reminder/escalation fields, `Status.FLAGGED`, `status_before_flag`; `NoteAppeal`, `NoteReport`; `NoteRating.owner_rewarded` |
| payments (new) | `PaymentOrder`, `WalletEntry`, `Wallet`, `WithdrawalRequest` |
| swaps (new) | `SkillPost`, `SwapSession`, `SessionRating` |
| courses | `Course` reshaped, `Lesson`, `PricingRule`; `CoursePurchase` gains commission fields; wallet and swap stubs removed |

## 6. URL additions (summary)

`/accounts/verify/<token>/`, `/accounts/profile/`, `/accounts/password/...`, `/notes/appeals/`, `/notes/flagged/`, `/notes/<id>/report/`, `/notifications/`, `/payments/credits/buy/`, `/payments/orders/`, `/payments/sandbox/<uuid>/`, `/credits/hollow/state/`, `/credits/ledger/`, `/swaps/...`, `/dashboard/`, `/courses/<id>/`, `/courses/<id>/learn/`, `/courses/lesson/<id>/stream/`, `/courses/manage/...`, `/payments/wallet/`, `/payments/withdrawals/`.

## Payment Gateway
- bKash PGW (Sandbox)

## 7. Out of scope for this release

React or any SPA framework, Celery or any always-on scheduler, calling Google Meet or Zoom APIs, admin-moderated content, credit-to-money withdrawal (never), automated refunds for courses.

## 8. Open decisions (the agent proceeds with the default and flags it in its report)

| # | Question | Default used |
|---|---|---|
| 1 | Product name: "Skillo" (plan) vs "Gayn Kotor" (current UI) | UI keeps "Gayn Kotor" via `SITE_NAME`; docs mention both |
| 2 | Does the university have its own email domain? | `ALLOWED_EMAIL_DOMAINS` empty; ID checking by CR/teacher is the safeguard |
| 3 | Exactly one class teacher per batch? | Yes (matches the `Batch.class_teacher` field) |
| 4 | Swap deposit of 10 credits each, forfeited to the attending party? | Yes, as specified in Phase 5 |
| 5 | Is the video-course pillar acceptable to the teacher? | Built behind `ENABLE_VIDEO_COURSES`, on in development |
| 6 | 1 BDT = 1 credit? | Yes (`CREDIT_PRICE_BDT`) |
| 7 | Per-hour price ranges | Placeholders: academic 50 to 150 BDT/h, non-academic 200 to 600 BDT/h; editable in admin |
| 8 | Platform commission | 10% |
| 9 | "First version" payment and wallet code | Not in the repo, so written fresh; if supplied, place under `legacy/` and adapt |
| 10 | Hollow scene: keep `video.mp4` or replace with SVG | Replace with SVG; keep the video file for rollback |
| 11 | Should teacher removal reverse the upload reward? | Optional checkbox, default off |

---

## 9. Verification commands (used by every phase)

Run from the project root with the virtualenv active. All must pass before a phase is reported done.

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test
```

Phase-specific extras:

| Phase | Extra command or manual check |
|---|---|
| 0 | `python manage.py move_private_files --dry-run`; try opening a note PDF by guessing its path under `/media/` (must fail) |
| 1 | In dev, signup prints a verification email in the terminal; click the link twice and check the ledger shows one bonus |
| 2 | `python manage.py send_reminders --dry-run` then `--now <ISO date 4 days ahead>`; open the review queue as CR and as class teacher |
| 3 | Buy 100 nuts via sandbox; replay the callback; balance rises once |
| 4 | `python manage.py check_ledger`; reverse an entry in admin; reload the hollow page and confirm no replay of seen entries |
| 5 | `python manage.py resolve_swaps`; book a session between two test users and run each outcome path |
| 6 | Log in as each role and confirm only that role's widgets appear |
| 7 | Upload a short MP4, check price range hint, buy via sandbox, stream with seeking, request a withdrawal |
| 8 | `python manage.py check --deploy`; `python manage.py seed_demo` on a fresh database |

## 10. Per-phase agent prompts

Use the reusable prompt in section 0, or these shorter forms.

| Phase | Prompt |
|---|---|
| 0 | "Execute PRD.md Phase 0 (Baseline audit and hardening). Write docs/AUDIT.md first, then tasks 0.2 to 0.6. Do not change features." |
| 1 | "Execute PRD.md Phase 1 (Accounts). Read docs/AUDIT.md first; skip any task the audit shows already exists but still add its tests." |
| 2 | "Execute PRD.md Phase 2 (Notes completion). Make all time logic depend on an injectable `now` so it can be tested." |
| 3 | "Execute PRD.md Phase 3 (Payments sandbox). The payments app must not import credits or courses; use the fulfiller registry." |
| 4 | "Execute PRD.md Phase 4 (Nut Hollow and ledger admin). Keep static/images/video.mp4 untouched." |
| 5 | "Execute PRD.md Phase 5 (Skill swap). Implement the deposit state machine exactly as the tables specify and test every path." |
| 6 | "Execute PRD.md Phase 6 (Dashboards and home). Gate course widgets behind ENABLE_VIDEO_COURSES." |
| 7 | "Execute PRD.md Phase 7 (Video courses). Stop and ask before adding mutagen. Streaming must support HTTP Range." |
| 8 | "Execute PRD.md Phase 8 (Hardening and docs). Generate README, ARCHITECTURE, ERD, Project_Proposal.md and Improvements.md." |

## 11. New dependencies

| Package | Phase | Reason | Rule |
|---|---|---|---|
| `mutagen` | 7 | Read MP4 duration in pure Python | Pin an exact version in `requirements.txt`; ask before adding |

No other new packages are expected. If an agent thinks it needs one, it must stop and ask.

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Paid files reachable by guessable URL | Paywall bypass | Phase 0 private storage plus UUID filenames |
| Double credit payment (race or replay) | Credit inflation | Row locks, idempotent fulfilment, tests per phase |
| Swap disputes with no moderator | Unfair outcomes | Contradiction returns both deposits; auto-resolve timer |
| Video pillar scope and teacher approval | Blocks final week | Feature flag; built last; core pillars work without it |
| Large video uploads on one server | Timeouts, disk use | Size limits, MP4 only, streaming upload handling, cloud storage listed in Improvements.md |
| Missing `accounts` and `campus` code in this PRD's inputs | Wrong assumptions | Phase 0 audit before any build |
| No scheduler | Late reminders | Lazy engine on page load plus runnable commands and cron lines |

## 13. Definition of done (whole project)

1. All phases 0 to 8 accepted; each phase's acceptance list passes.
2. `check`, `makemigrations --check`, `check --deploy` and `test` are clean.
3. No ledger or wallet balance is ever written directly; `check_ledger` reports nothing.
4. Every id-based URL has a permission test.
5. A fresh clone runs the demo from the README alone.
6. `Project_Proposal.md` follows the department format; `Improvements.md` lists future work.

## 14. Suggested timeline

Matches the plan's four weeks, with the work already finished in weeks 1 and 2 counted in.

| Week | Phases |
|---|---|
| 1 | 0, 1, 2 |
| 2 | 3, 4 |
| 3 | 5, 6 |
| 4 | 7, 8 |

If time runs short, drop Phase 7 (set `ENABLE_VIDEO_COURSES=False`) and keep Phase 8; the proposal then lists courses under future work.
