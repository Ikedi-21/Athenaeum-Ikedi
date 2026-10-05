# Athenaeum Ikedi Library System

Athenaeum Ikedi is a Django-based academic library management system. It supports public catalogue browsing, student accounts, reviews, borrowing, returning, renewals, reservations, fines, notifications, audit logging, and librarian management tools.

For the full detailed project documentation, see:

[docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md)

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_library
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

Main apps:

- `accounts`: users, roles, authentication, settings, student management.
- `catalog`: books, categories, reviews, search, catalogue administration.
- `circulation`: loans, returns, renewals, reservations, fines, audit logs.
- `dashboard`: role-based dashboard and persistent notifications.
