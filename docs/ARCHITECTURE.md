# Gayn Kotor — System Architecture

## 1. Architectural Overview & Design Principles

**Gayn Kotor** is an institutional campus knowledge-sharing and peer-learning platform built with a modular, decoupled architecture using **Django 6.1**, **PostgreSQL** (Neon Serverless), and modern frontend utilities (**Tailwind CSS**).

The architecture prioritizes:
- **Zero-Trust File Protection**: No academic notes or video files are directly accessible via public web server roots. Every byte served is verified against authenticated session permissions and access control policies.
- **Append-Only Financial Integrity**: Both the gamified internal micro-credit ledger (**Nut Hollow**) and the instructor real-currency wallet ledger (**Wallet**) are strictly immutable, append-only ledgers. Balances are derived from cryptographic-like ledger sums, and writes enforce row-level database locks (`SELECT ... FOR UPDATE`) to prevent double-spending.
- **Pluggable Payment Processing**: The payment infrastructure separates business domain logic (Credits, Courses) from payment collection via an in-memory fulfiller registry and gateway adapters.
- **Decentralized Hierarchical Moderation**: Peer moderation starts with student Class Representatives (CRs) and automatically escalates to faculty Class Teachers before applying deterministic fallback actions.

```mermaid
flowchart TD
    subgraph Client["Client Tier"]
        Browser["Modern Web Browser / Mobile Viewport"]
    end

    subgraph Gateway["Web & Reverse Proxy Tier"]
        Nginx["Nginx Reverse Proxy / SSL Termination"]
        StaticSrv["Static Files (CSS/JS/Icons)"]
    end

    subgraph App["Django Application Tier (WSGI / Gunicorn)"]
        SecMiddleware["Security & Auth Middleware (CSRF, HSTS, Session)"]
        Router["URL Router & View Dispatcher"]
        
        subgraph Apps["Modular Domain Apps"]
            Accounts["accounts (Auth, ID Verification)"]
            Campus["campus (Depts, Batches, CRs)"]
            Notes["notes (Upload, Review, Moderation)"]
            Credits["credits (Nut Hollow Micro-Ledger)"]
            Swaps["swaps (Peer Tutoring & Escrow)"]
            Payments["payments (Gateway Adapters, Wallet)"]
            Courses["courses (Video Marketplace, Range Streaming)"]
            Notifications["notifications (In-app Alerts)"]
        end
        
        FulfillerRegistry["Payment Fulfiller Registry"]
        PrivateStorage["Private File Access Manager (Sendfile / Range)"]
    end

    subgraph Storage["Persistence & Media Tier"]
        Postgres[("PostgreSQL Database (Neon)")]
        PrivateMedia[("Private Media Storage (Notes PDF & MP4 Lessons)")]
    end

    Browser <-->|HTTPS / HTTP Range| Nginx
    Nginx -->|Proxy Pass| SecMiddleware
    Nginx -->|Direct Serve| StaticSrv
    SecMiddleware --> Router
    Router --> Apps
    Payments <-->|Callbacks| FulfillerRegistry
    FulfillerRegistry -->|Topup / Enroll| Credits
    FulfillerRegistry -->|Course Grant| Courses
    Courses & Notes --> PrivateStorage
    PrivateStorage <-->|Buffered Chunk Read| PrivateMedia
    Apps <-->|SQL Queries & Transactions| Postgres
```

---

## 2. Modular Decoupling & App Responsibilities

To avoid circular dependencies and ensure strict maintainability, the codebase is segregated into 8 isolated Django apps:

| App | Core Responsibility | Key Invariants & Dependencies |
| :--- | :--- | :--- |
| **`accounts`** | Custom user model, 15-17 digit academic ID validation, signed email verification tokens. | Depends on nothing; foundational auth provider. |
| **`campus`** | Institutional hierarchy: Departments, Batches, Class Teachers, and CR Batch Memberships. | Depends only on `accounts`. |
| **`notes`** | PDF note submissions, PyMuPDF cover-page generation, view permissions, reporting, appeals. | Uses `campus` for batch routing, `credits` for rewards, and `notifications`. |
| **`credits`** | The **Nut Hollow** micro-credit ledger. Manages nuts economy, ledger transactions, and balance calculation. | Does not import `payments` or `courses`. |
| **`swaps`** | Peer-to-peer skill swap exchange. Enforces a 10-nut deposit escrow state machine and meeting link validation. | Depends on `credits` for deposit holding/forfeiture. |
| **`payments`** | Multi-gateway payment adapter (Sandbox, bKash, Nagad, SSLCommerz), PaymentOrders, instructor Wallet and Withdrawals. | Decoupled from `credits` and `courses` via `fulfiller_registry`. |
| **`courses`** | Video marketplace, mutagen duration validation, billable price limits, and HTTP Range partial streaming. | Gated behind `ENABLE_VIDEO_COURSES`. Registers fulfiller in `payments`. |
| **`notifications`** | Generic notification engine delivering user alerts and navbar badges. | Referenced by domain apps to notify actors. |

---

## 3. Nut Hollow Micro-Credit Ledger Architecture

The internal gamified economy uses **Nuts** as micro-credits. 

### Invariants:
1. **Append-Only Immutability**: Ledger entries are never updated or deleted. Corrective adjustments are recorded as new rows linked through the `reverses` foreign key.
2. **Double-Spend Protection**: Any operation subtracting credits (`amount < 0`) runs inside `@transaction.atomic`, acquires an exclusive database row lock on the user (`User.objects.select_for_update().get(pk=user.pk)`), and checks solvency before inserting the debit record.
3. **Per-Request Context Caching**: `get_balance(user, request=request)` caches the computed `SUM(amount)` on the `request` object during template rendering. Calling `add_entry` invalidates this cached value immediately.

```mermaid
sequenceDiagram
    autonumber
    actor Learner as Student (Learner)
    participant View as notes:note_download
    participant DB as PostgreSQL (Neon)
    participant Ledger as credits.services.add_entry
    participant File as notes.views.note_file

    Learner->>View: GET /notes/42/download/
    View->>DB: Check NoteDownload(user=Learner, note=42)
    alt Already Unlocked
        View->>File: Serve File Directly (No Cost)
    else First Download (Unlock Required)
        View->>DB: BEGIN TRANSACTION
        View->>DB: SELECT FOR UPDATE FROM accounts_user WHERE id = Learner.id
        View->>DB: SELECT SUM(amount) FROM credits_creditledger WHERE user_id = Learner.id
        alt Balance < 5 Nuts
            View-->>Learner: HTTP 403 Forbidden / Redirect (Insufficient Nuts)
        else Balance >= 5 Nuts
            View->>Ledger: Insert CreditLedger(-5, reason='note_download')
            View->>DB: Insert NoteDownload(user=Learner, note=42)
            View->>DB: UPDATE notes_note SET download_count = download_count + 1
            View->>DB: COMMIT TRANSACTION
            View-->>Learner: HTTP 302 Redirect to /notes/42/file/
            Learner->>File: GET /notes/42/file/
            File-->>Learner: HTTP 200 Binary PDF Stream
        end
    end
```

---

## 4. Payment Fulfiller Registry & Wallet Architecture

To prevent tight coupling between financial payments and product delivery, `payments` uses a runtime **Fulfiller Registry**:

```python
# payments/registry.py
_FULFILLERS = {}

def register_fulfiller(purpose: str, fulfiller_fn: Callable):
    _FULFILLERS[purpose] = fulfiller_fn

def get_fulfiller(purpose: str) -> Optional[Callable]:
    return _FULFILLERS.get(purpose)
```

1. When `credits` boots, `CreditsConfig.ready()` registers `fulfill_credit_topup` for `PaymentOrder.Purpose.CREDIT_TOPUP`.
2. When `courses` boots, `CoursesConfig.ready()` registers `fulfill_course_purchase` for `PaymentOrder.Purpose.COURSE`.
3. When any payment gateway marks an order as paid, `payments.services.fulfil_order()` looks up the fulfiller and invokes it with `order`.

### Creator Wallet & Cash Withdrawals
- Every paid course sale splits the payment: **10% platform commission** and **90% instructor earnings**.
- Instructor earnings are appended to `WalletEntry` (`reason='course_sale'`).
- When an instructor requests a cash withdrawal (`payments:withdrawals`):
  1. The user's `Wallet` row is locked using `select_for_update()`.
  2. The wallet balance `SUM(amount)` is verified against `WITHDRAW_MIN_BDT` (default 500 BDT).
  3. A negative `WalletEntry` with `reason='withdrawal_hold'` is written immediately in the same transaction.
  4. A `WithdrawalRequest` is created in `PENDING` state.
  5. Upon admin payment, the request transitions to `PAID`. If rejected, a reversing positive `WalletEntry` (`withdrawal_reversal`) is written.

---

## 5. Private Storage & HTTP Range Streaming

### Private Notes Storage
PDF files uploaded by students are saved under `PRIVATE_MEDIA_ROOT` (e.g. `private_media/notes/`). Public web servers are instructed not to serve this directory directly. When an authorized user requests the file, Django streams the file chunk by chunk (or issues an `X-Accel-Redirect` / `X-Sendfile` header when supported by the web server).

### Video Course HTTP Range Streaming (RFC 7233)
Video playback requires instantaneous seeking and scrubbing without downloading full MP4 files upfront.
`courses.views.lesson_stream` implements a standards-compliant HTTP Range parser:

```mermaid
sequenceDiagram
    actor Player as HTML5 Video Player
    participant StreamView as courses:lesson_stream
    participant Disk as Private Media (MP4)

    Player->>StreamView: GET /courses/lesson/7/stream/ (Header: "Range: bytes=0-1048575")
    StreamView->>StreamView: Verify Enrollment (CoursePurchase or Instructor/Superuser)
    StreamView->>Disk: Open file, seek to byte 0
    StreamView->>Disk: Read 1,048,576 bytes
    StreamView-->>Player: HTTP 206 Partial Content<br/>Accept-Ranges: bytes<br/>Content-Range: bytes 0-1048575/34591024<br/>Content-Length: 1048576<br/>Content-Type: video/mp4
    Player->>StreamView: GET /courses/lesson/7/stream/ (Header: "Range: bytes=20000000-21048575")
    StreamView->>Disk: Seek to byte 20,000,000 and read 1 MB
    StreamView-->>Player: HTTP 206 Partial Content (Next chunk)
```

---

## 6. Note Review Escalation Engine

Notes uploaded by students are held in `PENDING` status. The review queue implements a decentralized escalation lifecycle:

```mermaid
stateDiagram-v2
    [*] --> PENDING: Student Uploads Note
    
    state PENDING {
        [*] --> CR_Review: Days 0 - 2 (CR Notification)
        CR_Review --> Teacher_Escalated: Day 3+ (CR Reminded & Teacher Notified)
        Teacher_Escalated --> Auto_Published: Day 7+ (Unreviewed Fallback)
    }

    CR_Review --> APPROVED: CR or Teacher Approves (+10 Nuts Reward)
    Teacher_Escalated --> APPROVED: Teacher Approves (+10 Nuts Reward)
    Auto_Published --> UNVERIFIED: Published without reward
    
    CR_Review --> REJECTED: CR Rejects (Reason logged)
    Teacher_Escalated --> REJECTED: Teacher Rejects (Reason logged)
    
    REJECTED --> APPEAL_OPEN: Author Submits Appeal
    APPEAL_OPEN --> APPROVED: Teacher Grants Appeal (+10 Nuts)
    APPEAL_OPEN --> REJECTED: Teacher Upholds Rejection
    
    APPROVED --> FLAGGED: 3+ Community Reports
    UNVERIFIED --> FLAGGED: 3+ Community Reports
    FLAGGED --> APPROVED: Teacher Dismisses Flag
    FLAGGED --> REMOVED: Teacher Confirms Violation (Reward Clawback)
    
    APPROVED --> [*]
    UNVERIFIED --> [*]
    REMOVED --> [*]
```

---

## 7. Skill Swap Escrow & Deposit State Machine

The **swaps** engine implements an escrow state machine to protect peer-to-peer commitments.

```mermaid
stateDiagram-v2
    [*] --> REQUESTED: Learner Requests Session
    
    REQUESTED --> DECLINED: Teacher Declines (No Cost)
    REQUESTED --> ACCEPTED: Teacher Proposes Time
    
    ACCEPTED --> SCHEDULED: Learner Confirms Time<br/>[10 Nuts Held from Both]
    
    state SCHEDULED {
        [*] --> Awaiting_Meeting: Teacher Sets Meeting Link (Meet/Zoom/Teams)
        Awaiting_Meeting --> Session_Active: Scheduled Start Time Arrives
    }

    SCHEDULED --> CANCELLED: Cancel >24h Before<br/>[Both Deposits Returned]
    SCHEDULED --> NO_SHOW: Cancel <24h Before<br/>[Canceller Forfeits 10, Victim gets 20]
    
    Session_Active --> COMPLETED: Both Report 'Completed'<br/>[Both Deposits Returned]
    Session_Active --> NO_SHOW: Uncontested No-Show after 24h<br/>[Innocent gets 20, No-Show loses 10]
    Session_Active --> DISPUTED: Contradictory Outcomes Reported<br/>[Both Deposits Returned for Safety]
    
    COMPLETED --> [*]
    NO_SHOW --> [*]
    CANCELLED --> [*]
    DISPUTED --> [*]
```

---

## 8. Web Security & IDOR Defense Matrix

The application implements zero-trust defense against Insecure Direct Object References (IDOR), cross-site scripting (XSS), and cross-site request forgery (CSRF):

1. **Anti-Enumeration 404 Responses**: Unauthorized attempts to inspect unapproved, rejected, or private notes return `HTTP 404 Not Found` rather than `403 Forbidden` to prevent private identifier probing.
2. **Strict Object-Level Permissions**: Every view fetching models with primary keys verifies authorization against `request.user`:
   - Notes: visible only if approved, owned, or user holds a review seat in the author's batch.
   - Orders: visible only to order owner or superuser.
   - Video Streaming: requires confirmed `CoursePurchase` record or instructor ownership.
   - Swap Meeting Links: hidden until session status is `SCHEDULED`.
   - Withdrawal Requests: viewable and creatable only by wallet owner.
3. **Production Hardening**:
   - `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, `SESSION_COOKIE_HTTPONLY = True`.
   - `SECURE_HSTS_SECONDS = 31536000`, `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`, `SECURE_HSTS_PRELOAD = True`.
   - `SECURE_CONTENT_TYPE_NOSNIFF = True`, `X_FRAME_OPTIONS = "DENY"`.
