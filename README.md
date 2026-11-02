# Gayn Kotor (জ্ঞান কোটর)

**A Decentralized Campus Knowledge Exchange & Peer Learning Platform**

Gayn Kotor is a production-grade campus academic web platform built with **Django 6.1**, **PostgreSQL** (Neon Serverless), and **Tailwind CSS**. It bridges the gap in university knowledge sharing by providing:
- **Verified Academic Notes**: Peer and faculty-curated lecture notes with automated reminder escalation and community flag moderation.
- **Nut Hollow Micro-Credit Economy**: An immutable, append-only gamified credit ledger with double-spend protection.
- **Skill Swap Tutoring Escrow**: Peer-to-peer 1-on-1 tutoring sessions backed by a 10-nut commitment deposit and automated no-show arbitration.
- **Video Course Marketplace**: Creator courses with duration-based price guardrails, instructor revenue share (90%), and RFC 7233-compliant **HTTP Range partial video streaming**.

---

## Architecture & System Documentation

- [System Architecture Specification](docs/ARCHITECTURE.md)
- [Entity-Relationship Diagram (ERD)](docs/ERD.md)
- [BSc Computer Engineering Project Proposal](Project_Proposal.md)
- [Future Improvements & Scalability Roadmap](Improvements.md)

---

## Prerequisites

- **Python**: 3.12 or newer (Tested on Python 3.14)
- **Database**: PostgreSQL 15+ (Local or cloud Neon database)
- **Git**

---

## Quickstart: Setup From Scratch

Follow these steps to run a fresh clone locally:

### 1. Clone & Navigate
```bash
git clone https://github.com/your-username/gayn_kotor.git
cd gayn_kotor
```

### 2. Create & Activate Virtual Environment
**On Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```
**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your database credentials and secret key. For local development with PostgreSQL, specify `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`.

### 5. Apply Database Migrations
```bash
python manage.py migrate
```

### 6. Seed Demo Data (Development Only)
Populate realistic departments, batches, lecturers, students, notes in multiple review states, skill swap sessions, and video courses:
```bash
python manage.py seed_demo
```
*(Note: `seed_demo` is idempotent and safely refuses to run when `DEBUG=False`.)*

### 7. Run the Development Server
```bash
python manage.py runserver
```
Visit **http://127.0.0.1:8000/** in your browser.

---

## Demo Accounts & Credentials

All seeded demo accounts share the password: **`Password123!`**

| Username | Role | Department / Batch | Purpose |
| :--- | :--- | :--- | :--- |
| **`admin`** | Superuser / Admin | Campus-wide | Platform administration & moderation |
| **`prof.rahim`** | Lecturer / Class Teacher | CSE / Batch 2023 | Course author, reviews escalated notes |
| **`prof.karim`** | Lecturer / Class Teacher | EEE / Batch 2024 | Faculty reviewer |
| **`cr.cse`** | Student (CR) | CSE / Batch 2023 | Class Representative review queue |
| **`student.alice`** | Student | CSE / Batch 2023 | Note author, skill mentor, course buyer |
| **`student.bob`** | Student | CSE / Batch 2023 | Note downloader, reviewer, skill learner |
| **`student.charlie`** | Student | EEE / Batch 2024 | Circuit mentor, skill swap participant |
| **`student.pending`** | Student | Pending Batch | Demonstrates pending membership state |

---

## Core Management Commands

Gayn Kotor includes specialized management commands for system operations and scheduled maintenance:

### 1. Seed Demo Data
```bash
python manage.py seed_demo
```
Seeds departments (CSE, EEE, BBA), batches, teachers, CRs, students, sample notes with different ages, swap sessions in various states, video lessons, and sandbox transactions.

### 2. Review Queue Reminders & Escalations
```bash
python manage.py send_reminders
```
Evaluates pending notes against age thresholds:
- **Age $\ge$ 2 days**: Sends reminder notification to batch Class Representatives.
- **Age $\ge$ 4 days**: Escalates note to the faculty Class Teacher.
- **Age $\ge$ 7 days**: Auto-publishes unreviewed notes as `UNVERIFIED` (fallback).

**Demonstration Flags:**
- `--dry-run`: Simulates execution without persisting database changes.
- `--now ISO_TIMESTAMP`: Overrides the system clock to simulate future dates (e.g., `--now 2026-11-05T12:00:00Z`).

### 3. Skill Swap Auto-Resolution & Dispute Expiration
```bash
python manage.py resolve_swaps
```
Processes scheduled swap sessions:
- Returns deposits when both participants report `COMPLETED`.
- Awards deposit return + forfeit compensation (20 nuts total) to the innocent party when a no-show goes uncontested for 24 hours.
- Returns both deposits safely when contradictory outcomes are filed (`DISPUTED`).

### 4. Financial Ledger Audit & Integrity Check
```bash
python manage.py check_ledger
```
Audits every user's `CreditLedger` and verifies that no account has a negative balance or broken reversal linkage.

### 5. Private Files Migration
```bash
python manage.py move_private_files
```
Audits and moves existing public-facing media files into the protected `PRIVATE_MEDIA_ROOT` directory.

---

## How to Demo the Review Escalation Workflow

To demonstrate the automated peer-to-faculty review escalation in real time:

1. **Upload a Note**: Log in as `student.alice` and upload a new note at `/notes/upload/`. The note status starts as `PENDING`.
2. **Day 2 CR Reminder**:
   Run:
   ```bash
   python manage.py send_reminders --now 2026-11-03T12:00:00Z
   ```
   Log in as `cr.cse` to see the review reminder in notifications.
3. **Day 4 Teacher Escalation**:
   Run:
   ```bash
   python manage.py send_reminders --now 2026-11-05T12:00:00Z
   ```
   Log in as `prof.rahim` to see the escalated review item in the faculty queue.
4. **Teacher Approval**:
   `prof.rahim` reviews and clicks **Approve**. `student.alice` immediately receives +10 Nuts in her Nut Hollow balance.

---

## Running Automated Tests

Run the complete test suite (Unit tests, IDOR Security matrix, and E2E scenario lifecycle):

```bash
python manage.py test --keepdb
```

To run individual test suites:
```bash
# Security & IDOR Access Control Matrix
python manage.py test --keepdb core.test_security_matrix

# Full User Lifecycle End-to-End Scenarios
python manage.py test --keepdb core.test_scenarios

# Domain App Suites
python manage.py test --keepdb notes
python manage.py test --keepdb swaps
python manage.py test --keepdb courses
python manage.py test --keepdb payments
python manage.py test --keepdb credits
```

---

## Production Deployment & Operations

### Deployment Readiness Check
Verify production security settings with `DEBUG=False`:
```bash
python manage.py check --deploy
```

### Production Crontab Setup
Configure periodic maintenance tasks via cron:
```cron
# Evaluate review reminders and escalations every 6 hours
0 */6 * * * /path/to/venv/bin/python /path/to/gayn_kotor/manage.py send_reminders >> /var/log/gayn_kotor_reminders.log 2>&1

# Resolve swap sessions and dispute expirations hourly
0 * * * * /path/to/venv/bin/python /path/to/gayn_kotor/manage.py resolve_swaps >> /var/log/gayn_kotor_swaps.log 2>&1

# Daily ledger integrity audit
0 3 * * * /path/to/venv/bin/python /path/to/gayn_kotor/manage.py check_ledger >> /var/log/gayn_kotor_ledger.log 2>&1
```

### Gunicorn & Nginx Configuration

**Gunicorn Systemd Unit (`/etc/systemd/system/gayn_kotor.service`):**
```ini
[Unit]
Description=Gayn Kotor Gunicorn Application Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/gayn_kotor
ExecStart=/var/www/gayn_kotor/venv/bin/gunicorn \
    --workers 4 \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/gayn_kotor/access.log \
    --error-logfile /var/log/gayn_kotor/error.log \
    config.wsgi:application

[Install]
WantedBy=multi-user.target
```

**Nginx Server Block (`/etc/nginx/sites-available/gayn_kotor`):**
```nginx
server {
    listen 80;
    server_name campus.edu;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name campus.edu;

    ssl_certificate /etc/letsencrypt/live/campus.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/campus.edu/privkey.pem;

    client_max_body_size 100M;

    # Static Assets (CSS, JS, Fonts, Public Images)
    location /static/ {
        alias /var/www/gayn_kotor/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    # Protected Private Media (Internal Only)
    location /private_media/ {
        internal;
        alias /var/www/gayn_kotor/private_media/;
    }

    # WSGI Reverse Proxy
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Database Backup & Restore

**Automated PostgreSQL Backup:**
```bash
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME -F c -b -v -f /backups/gayn_kotor_$(date +%Y%m%d_%H%M%S).dump
```

**Restore:**
```bash
pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME -v /backups/gayn_kotor_backup.dump
```

---

## License

This project is developed for institutional academic use under the MIT License.

