# Local Development Setup Guide

This guide walks you through setting up and running **Gayn Kotor** locally on your development machine.

---

## 1. System Requirements & Prerequisites

Before you start, make sure you have the following installed:

- **Python**: Version `3.12` or higher (tested up to `3.14`).
- **PostgreSQL**: Version `14` or higher installed and running.
- **Git**: For version control.
- **Virtual Environment**: Python's built-in `venv` module.

---

## 2. Quickstart Overview

1. [Clone Repository](#3-clone-the-repository)
2. [Create & Activate Virtual Environment](#4-set-up-virtual-environment)
3. [Install Dependencies](#5-install-python-dependencies)
4. [Set Up PostgreSQL Database](#6-configure-postgresql-database)
5. [Configure Environment Variables (`.env`)](#7-configure-environment-variables)
6. [Apply Migrations](#8-apply-database-migrations)
7. [Create Superuser](#9-create-a-superuser)
8. [Seed Initial Campus Data](#10-initial-data-setup-crucial-for-student-signup)
9. [Run the Development Server](#11-start-the-development-server)

---

## 3. Clone the Repository

Clone the project to your local machine and switch to the project directory:

```bash
git clone <repository-url>
cd gayn_kotor
```

---

## 4. Set Up Virtual Environment

It is recommended to use an isolated Python virtual environment.

### Windows (PowerShell)
```powershell
# Create virtual environment
py -m venv venv

# If PowerShell script execution is restricted, run:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Activate virtual environment
.\venv\Scripts\Activate.ps1
```

### Windows (Command Prompt - CMD)
```cmd
py -m venv venv
venv\Scripts\activate.bat
```

### Linux / macOS (Bash / Zsh)
```bash
python3 -m venv venv
source venv/bin/activate
```

*(When activated, your shell prompt will show `(venv)` at the beginning).*

---

## 5. Install Python Dependencies

Make sure `pip` is updated to the latest version, then install the dependencies listed in `requirements.txt`:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note on Dependencies:**
> - `psycopg[binary]`: High-performance PostgreSQL driver for Django.
> - `pymupdf` (`fitz`): Used to render PDF first-page preview thumbnails for uploaded course notes.
> - `python-dotenv`: Loads `.env` configuration into environment variables.

---

## 6. Configure PostgreSQL Database

Ensure your local PostgreSQL server is running.

### Create Database
Open your terminal / SQL client (such as `psql`, pgAdmin, or DBeaver):

```bash
psql -U postgres
```

Inside the PostgreSQL prompt, create the database:

```sql
CREATE DATABASE gayn_kotor;
```

*(You can type `\q` to exit `psql`).*

---

## 7. Configure Environment Variables

Create your `.env` file from the provided example template:

### Windows (PowerShell)
```powershell
Copy-Item .env.example .env
```

### Linux / macOS
```bash
cp .env.example .env
```

### Update `.env` Settings
Open `.env` in your text editor and adjust the values according to your local configuration:

```env
SECRET_KEY=django-insecure-local-dev-secret-key-change-me
DEBUG=True
DB_NAME=gayn_kotor
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432
```

> **Tip - Generating a Secret Key:**
> You can generate a secure secret key using Python:
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(50))"
> ```

---

## 8. Apply Database Migrations

Apply the existing migrations to create all database tables:

```bash
python manage.py migrate
```

---

## 9. Create a Superuser

Create an administrative account to access the Django Admin dashboard:

```bash
python manage.py createsuperuser
```

Follow the prompts for:
- **Username**
- **Email address**
- **Password**

*(Superuser accounts automatically bypass standard student/lecturer ID format checks).*

---

## 10. Initial Data Setup (Crucial for Student Signup)

> **Important:**
> The student registration form requires selecting a **Batch** (e.g., `CSE - Batch 54`). Therefore, before registering student users, you should create at least one **Department** and **Batch** in the system.

### Option A: Via Django Admin Dashboard (Recommended)
1. Start the server (see next step) and visit: `http://127.0.0.1:8000/admin/`.
2. Under the **Campus** section:
   - Click **Departments** &rarr; **Add Department** (e.g., Name: `Computer Science and Engineering`, Code: `CSE`).
   - Click **Batches** &rarr; **Add Batch** (e.g., Name: `54th Batch`, Department: `Computer Science and Engineering`).

### Option B: Quick Shell Seed Command
Alternatively, run this one-line command to populate sample campus data:

```bash
python manage.py shell -c "from campus.models import Department, Batch; d, _ = Department.objects.get_or_create(name='Computer Science & Engineering', code='CSE'); Batch.objects.get_or_create(department=d, name='Batch 54'); print('Created sample department and batch.')"
```

---

## 11. Start the Development Server

Run the built-in development server:

```bash
python manage.py runserver
```

Open your browser and navigate to:
- **Website Home**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Admin Dashboard**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 12. Key Local Testing Workflows

### User Accounts
- **Student Accounts**:
  - Student IDs must be **15 to 17 numeric digits** (e.g., `011211054123456`).
  - Upon signing up, students automatically receive **30 bonus credits (nuts)**.
  - Joining a batch places membership into `pending` status until approved by a class teacher or CR.
- **Lecturer Accounts**:
  - Teacher IDs must be **3 to 30 alphanumeric characters** (can include hyphens).
  - Newly created Lecturer accounts are set to `is_active=False` and must be activated by an admin via Django Admin.

### Uploading & Reviewing Notes
- Upload a `.pdf` file under `/notes/upload/`.
- The system automatically triggers `make_preview()` via PyMuPDF to extract page 1 as a JPEG thumbnail stored in `media/notes/previews/`.
- Class teachers and approved CRs of the batch can view and approve notes under `/notes/review/`.
- Note authors earn an upload reward (10 credits) once approved.

### Automated Publishing of Overdue Notes
Gayn Kotor includes a management command to auto-publish notes that have passed the review window (defined by `NOTE_AUTOPUBLISH_DAYS = 7` in `config/settings.py`):

```bash
python manage.py publish_overdue
```

*(You can configure this command to run via a cron job or scheduled task in production/staging environments).*

### Email Notifications
In development, email delivery is configured to use the console backend:
```python
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
```
Any outgoing emails (notifications, alerts) are printed directly to the terminal where `runserver` is active.

---

## 13. Troubleshooting & FAQs

### 1. `psycopg.OperationalError: connection to server at "localhost" failed`
- **Cause**: PostgreSQL service is not running or connection credentials in `.env` are incorrect.
- **Fix**:
  - Check if PostgreSQL service is running:
    - **Windows**: Open `services.msc` and ensure `postgresql-x64-<version>` is running.
    - **Linux**: `sudo systemctl status postgresql`
    - **macOS**: `brew services list`
  - Verify `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in your `.env` file.

### 2. `ExecutionPolicy` Error on Windows PowerShell
- **Cause**: Script execution is disabled on the current Windows machine.
- **Fix**: Run in an elevated PowerShell terminal or current user scope:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

### 3. Student Signup Error: *"Please select your batch"*
- **Cause**: No batches exist in the database.
- **Fix**: Log into `/admin/` with your superuser account and add a Department and Batch, or run the seed command from [Section 10](#10-initial-data-setup-crucial-for-student-signup).

### 4. Lecturer cannot log in after signup
- **Cause**: By default, lecturers require admin approval (`is_active` is set to `False`).
- **Fix**: An admin must go to `/admin/accounts/user/`, find the lecturer, check **Active**, and save.

### 5. Static Files or Styles Not Loading
- **Tailwind CSS**: The application uses the Tailwind CDN directly in templates. Make sure you have an active internet connection when running locally.
- **Static Assets**: Custom static assets reside in `static/` and are automatically served during local development when `DEBUG=True`.

