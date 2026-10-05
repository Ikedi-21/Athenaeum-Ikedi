# Athenaeum Ikedi Library System Documentation

## 1. Project Overview

Athenaeum Ikedi is a Django-based library management system for an academic library. It supports public catalogue browsing, student registration, book reviews, borrowing, returning, renewals, reservations, overdue fines, librarian catalogue management, student monitoring, audit logging, notifications, and a role-aware dashboard.

> Comment: In simple terms, this project is trying to behave like a real school library desk. A student can search for books and borrow them, while a librarian gets the tools needed to manage the shelves and keep track of what is happening.

The application is organized as a classic multi-app Django project. Each app owns one major responsibility:

- `accounts`: user accounts, authentication, registration, profile settings, student directory, and roles.
- `catalog`: books, categories, reviews, public catalogue pages, and librarian catalogue management.
- `circulation`: borrowing, returning, renewing, reservations, fines, and audit logging.
- `dashboard`: student/librarian dashboard data and persistent in-app notifications.
- `config`: project settings, root URL routing, WSGI, and ASGI configuration.

The system is designed around two main user roles:

- Student: browses books, borrows available books, reserves unavailable books, renews eligible loans, returns books, reviews books, views notifications, and updates personal settings.
- Librarian: manages books and categories, monitors loans and fines, marks fines as paid, views audit logs, and views student details.

> Comment: The role split is one of the most important parts of the system. Students should not accidentally get management powers, and librarians should not have to use student-only workflows to do their work.

## 2. Technology Stack

The project uses:

- Python with Django 6.1.1
- SQLite for local development by default
- PostgreSQL-compatible configuration through `DATABASE_URL`
- WhiteNoise for production static file serving
- Gunicorn for production process serving
- `python-decouple` for environment variables
- `dj-database-url` for database configuration
- `django-ratelimit` for login, registration, password reset, and circulation action rate limits
- Argon2 password hashing
- Pillow for image uploads
- ReportLab is included in dependencies, likely for document/PDF-related generation support

The dependency list is stored in `requirements.txt`.

> Comment: The stack is practical for a Django school project because it can run locally with SQLite, but it is also prepared for a more serious deployment using PostgreSQL, Gunicorn, and WhiteNoise.

## 3. Project Structure

Important top-level files and folders:

```text
athenaeum_ikedi/
  manage.py
  requirements.txt
  Procfile
  pytest.ini
  .env.example
  accounts/
  catalog/
  circulation/
  dashboard/
  config/
  templates/
  static/
  docs/
```

Key directories:

- `accounts/`: user model, forms, login/register views, account settings views, librarian student management views, and role helpers.
- `catalog/`: book/category/review models, catalogue views, librarian management views, ISBN validation, forms, templates, and seed command.
- `circulation/`: borrowing services, rules, exceptions, reservation logic, audit log, loan desk views, middleware, and signals.
- `dashboard/`: notification model, dashboard views, context processors, and dashboard utility queries.
- `templates/`: shared and app-specific HTML templates.
- `static/`: CSS, JavaScript, logos, favicons, and images.
- `docs/`: existing PDF/DOCX documentation and brand assets.

> Comment: The folder layout is easy to follow because each app has a clear responsibility. This makes it easier to explain the project during review and easier to maintain later.

## 4. Installation and Local Setup

### 4.1 Requirements

Install Python and ensure `pip` is available. The project expects a normal Django environment.

> Comment: This setup assumes the person running the project already has Python installed. The project itself does not require a complicated local server stack before it can start.

### 4.2 Create a Virtual Environment

From the project folder:

```powershell
cd athenaeum_ikedi
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 4.3 Install Dependencies

```powershell
pip install -r requirements.txt
```

### 4.4 Configure Environment Variables

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Required variables:

- `SECRET_KEY`: Django cryptographic signing key.
- `DEBUG`: `True` for local development, `False` for production.
- `ALLOWED_HOSTS`: comma-separated hostnames, for example `127.0.0.1,localhost`.

Optional deployment variables supported by the settings:

- `DATABASE_URL`: database connection string. If absent, SQLite is used.
- `CSRF_TRUSTED_ORIGINS`: comma-separated HTTPS origins for deployment.
- `MEDIA_ROOT`: custom upload storage path.

> Comment: The `.env` file is where machine-specific and secret values belong. It should not be committed with real production secrets.

### 4.5 Run Migrations

```powershell
python manage.py migrate
```

### 4.6 Create an Admin/Librarian Account

```powershell
python manage.py createsuperuser
```

The custom user manager automatically assigns the `librarian` role to superusers.

> Comment: This is a helpful safeguard. Without it, a superuser might exist in Django but still be treated like a student by the project's own role checks.

### 4.7 Seed Sample Library Data

The project includes a management command:

```powershell
python manage.py seed_library
```

Use this to populate the catalogue with starter categories/books if needed.

### 4.8 Run the Development Server

```powershell
python manage.py runserver
```

Local site:

```text
http://127.0.0.1:8000/
```

> Comment: Once the server is running, the browser is the easiest way to test the whole workflow: register, log in, browse books, borrow, return, and check the dashboard.

## 5. Environment and Settings

The settings file is `config/settings.py`.

> Comment: This file controls how the project behaves in development and production, so it is one of the first places to check when the app fails to start or behaves differently after deployment.

### 5.1 Security Defaults

The project intentionally relies on Django's modern security defaults where appropriate, including HTTP-only sessions, SameSite cookies, frame protection, content type sniffing protection, and same-origin referrer behavior.

The project adds or configures:

- `SECRET_KEY` loaded from environment.
- `DEBUG` loaded from environment and defaulting to `False`.
- `ALLOWED_HOSTS` loaded from environment.
- `CSRF_TRUSTED_ORIGINS` loaded from environment.
- Argon2 as the preferred password hasher.
- Strong password validation with minimum length of 10.
- Site-wide login protection through `LoginRequiredMiddleware`.
- Public-page exemptions through `login_not_required`.
- Content Security Policy through Django's native CSP support.
- HTTPS redirects, HSTS, secure cookies, and proxy SSL handling when `DEBUG=False`.

> Comment: The security setup is not just decoration. A lot of common web mistakes are avoided here by making login required by default and only opening public pages deliberately.

### 5.2 Database

Database configuration uses `dj_database_url.config()`.

Default local database:

```text
sqlite:///db.sqlite3
```

Production database:

```text
DATABASE_URL=postgresql://...
```

SQLite gets a timeout option of 20 seconds for local development.

> Comment: SQLite is convenient while building and presenting the project, but PostgreSQL is the better choice when more than one person may be using the system at the same time.

### 5.3 Static and Media Files

Static files:

- `STATIC_URL = "static/"`
- `STATICFILES_DIRS = [BASE_DIR / "static"]`
- `STATIC_ROOT = BASE_DIR / "staticfiles"`
- WhiteNoise compressed manifest storage is used for collected static files.

Media uploads:

- `MEDIA_URL = "media/"`
- `MEDIA_ROOT` defaults to `BASE_DIR / "media"` and can be overridden with the environment.

In development, uploaded media is served through a special `serve_media` wrapper that is exempt from login requirements so public catalogue book covers can load for anonymous visitors.

> Comment: This small media-serving detail matters because the public catalogue should still look complete to visitors who are not signed in.

### 5.4 Authentication Redirects

- Login URL: `accounts:login`
- Login success: `dashboard:home`
- Logout success: `catalog:book_list`

Sessions last one week and refresh on active use.

> Comment: The redirect choices make sense for the user journey: after login the user goes to the dashboard, and after logout they return to the public book list.

## 6. Applications

## 6.1 Accounts App

The accounts app manages users, roles, authentication, profile settings, and librarian access to student records.

> Comment: This app is the identity layer of the project. Once the account and role are known, the rest of the system can decide what the user is allowed to do.

### Main Model: `User`

`accounts.models.User` extends Django's `AbstractUser`.

Custom fields:

- `role`: either `student` or `librarian`.
- `email`: required and unique.

Important properties:

- `is_student`: true when role is `student`.
- `is_librarian`: true when role is `librarian`.
- `user_settings`: returns or creates the related `UserSettings` row.

Important behavior:

- New users default to `student`.
- Superusers created with `createsuperuser` become librarians automatically.
- Role checks are centralized through properties so views/templates do not compare raw strings.

> Comment: Defaulting new users to students is the safer option. A mistake should never accidentally create a librarian account.

### User Settings

`UserSettings` stores per-user preferences:

- `bio`
- `phone_number`
- email loan notifications
- email overdue notifications
- digest frequency
- theme choice
- timezone
- date format
- MFA enabled flag

The current MFA field records status only; the code shown does not implement a complete second-factor authentication flow.

> Comment: The settings model gives the project room to grow. Some fields already work as preferences, while others look like planned enterprise features.

### System Configuration

`SystemConfig` stores platform-wide configuration as a singleton row.

Fields include:

- loan duration days
- maximum books per student
- fine rate per day
- student reservation toggle
- maintenance mode
- session timeout
- API access enabled flag
- primary API key
- webhook URL
- subscription tier
- storage allocation/usage
- maximum active members

Important note: current circulation rules in `circulation/rules.py` use constants such as `LOAN_PERIOD_DAYS`, `MAX_ACTIVE_LOANS`, and `FINE_PER_DAY`. The `SystemConfig` model exists, but the observed service code does not yet use it as the live policy source.

> Comment: This is worth pointing out clearly because someone might assume changing `SystemConfig` automatically changes borrowing behavior. Right now, the live rules still come from the constants file.

### Authentication Views

The project uses Django's built-in auth views where possible and customizes only what is needed.

Main views:

- `RegisterView`: public student signup.
- `LibraryLoginView`: login page with rate limiting.
- `LibraryLogoutView`: POST-only logout with a flash message.
- `PasswordResetRequestView`: password reset request with rate limiting and account enumeration protection.

Rate limits:

- Login by IP: 10 attempts per 5 minutes.
- Login by username: 5 attempts per 5 minutes.
- Registration by IP: 5 per hour.
- Password reset by IP: 15 per hour.
- Password reset by email: 5 per hour.

> Comment: These limits help prevent brute-force login attempts, fake account creation, and password reset abuse without making the normal user flow difficult.

### Account URLs

Mounted under `/accounts/`:

- `/accounts/register/`
- `/accounts/login/`
- `/accounts/logout/`
- `/accounts/password/change/`
- `/accounts/password/change/done/`
- `/accounts/password/reset/`
- `/accounts/password/reset/sent/`
- `/accounts/password/reset/<uidb64>/<token>/`
- `/accounts/password/reset/complete/`
- `/accounts/manage/students/`
- `/accounts/manage/students/<pk>/`
- `/accounts/settings/`
- `/accounts/privacy/`
- `/accounts/terms/`
- `/accounts/security/`

> Comment: Keeping account URLs under one namespace makes the project easier to reason about. Anything identity-related starts with `/accounts/`.

## 6.2 Catalog App

The catalog app manages books, categories, reviews, browsing, searching, filtering, and librarian catalogue administration.

> Comment: This is the part of the system users will probably interact with the most. It is also the part that makes the project feel like a real library rather than only an admin panel.

### Category Model

Fields:

- `name`: unique category name.
- `slug`: unique URL slug.
- `description`: optional text.

Behavior:

- The slug is generated from the name on first save.
- Existing slugs are not automatically changed during rename, protecting bookmarks and category URLs.
- Categories are ordered by name.
- Delete protection is applied indirectly through `Book.category` using `PROTECT`.

> Comment: Keeping slugs stable is a small but professional decision. It means links do not break just because a librarian corrects a category name.

### Book Model

Fields:

- `title`
- `author`
- `isbn`
- `category`
- `published_date`
- `description`
- `quantity`
- `available_quantity`
- `cover_image`
- `digital_url`
- `digital_file`
- `added_date`
- `is_active`

Important constraints:

- ISBN is unique.
- `available_quantity` cannot exceed `quantity`.
- `PositiveIntegerField` prevents negative quantity values.

Important properties:

- `is_available`: true when active and at least one copy is available.
- `borrowed_count`: total copies minus available copies.
- `bare_isbn_clean`: normalized ISBN.
- `open_library_url`: external Open Library lookup.
- `internet_archive_url`: Internet Archive ISBN search.
- `effective_digital_url`: uploaded file URL, external digital URL, or Open Library fallback.
- `has_custom_digital`: true when a librarian provided a file or URL.

Important behavior:

- Books are withdrawn with `is_active=False` rather than deleted, preserving loan history.
- Public catalogue pages hide inactive books.
- Librarian management pages include inactive books so they can be restored.

> Comment: Withdrawing instead of deleting is exactly what a library system should do. A book may leave the shelf, but its borrowing history should still remain trustworthy.

### Review Model

Fields:

- `book`
- `student`
- `rating`
- `comment`
- `created_date`

Rules:

- Rating must be from 1 to 5.
- One review per student per book.
- Reviews are ordered newest first.
- Reviews are deleted if the related book is deleted.

Average ratings are not stored on `Book`; they are calculated by query annotations.

> Comment: Calculating averages from the real review rows avoids stale rating data. If a review changes, the displayed average follows automatically.

### Catalog Forms

`BookForm`:

- Used by librarians to add/edit books.
- Exposes title, author, ISBN, category, publication date, description, quantity, cover, digital URL, and digital file.
- Does not expose `available_quantity` because circulation logic owns it.
- Does not expose `is_active` because withdrawal/restoration are separate workflows.
- Normalizes ISBNs before saving.
- Prevents quantity from being lower than copies currently on loan.
- Allows digital uploads with `.pdf`, `.epub`, or `.mobi` extensions. The validation error text currently says PDF or EPUB, so the wording should be updated if MOBI remains allowed.

> Comment: The form protects the librarian from accidentally creating impossible inventory, like saying the library owns fewer copies than are already out on loan.

`CategoryForm`:

- Used by librarians to create/edit subject headings.
- Prevents invalid or duplicate slugs that would be generated from the name.

`ReviewForm`:

- Used by students to add/edit a review.
- Uses a rating dropdown from 1 to 5.
- Receives book and student from the view rather than hidden form fields.
- Prevents duplicate reviews with a form-level error before the database constraint is hit.

> Comment: Passing book and student from the server side is safer than trusting hidden form inputs from the browser.

### Public Catalogue Views

`BookListView`:

- Public catalogue.
- Shows active books only.
- Supports search, category filtering, sorting, pagination, rating count, and average rating.
- Pagination size: 12 books per page.

`CategoryBookListView`:

- Public category page.
- Uses category slug in the URL.
- Returns 404 for missing category slug.

`BookDetailView`:

- Public detail page.
- Shows book metadata, reviews, average rating, review count, and digital access state.
- Allows authenticated students to add or edit their review.
- Prevents librarians from reviewing.
- Allows digital reading when the user has an active loan, is a librarian, or is a superuser.

> Comment: The public pages are open enough for discovery, while actions that change data still require the right user and role.

### Search, Filter, and Sort

Search checks:

- title
- author
- normalized ISBN

Sort options:

- newest
- title
- author
- rating
- popular

Security note:

Sort fields are whitelisted in `SORT_OPTIONS`. Query string input is never passed directly to `order_by()`, which prevents data leakage through arbitrary related-field ordering.

> Comment: This is one of those quiet security details that is easy to miss. The dropdown may look simple, but the code is careful about what it allows into the database query.

### Librarian Catalogue Views

`BookManageListView`:

- Shows all books, including withdrawn books.
- Reuses public search/filter/sort behavior.

`BookCreateView`:

- Adds a new book.
- Sets `available_quantity` equal to `quantity`.

`BookUpdateView`:

- Edits an existing book.
- Locks the book row during save.
- Recalculates available copies based on current copies on loan.
- Prevents total quantity from dropping below current loans.

`BookWithdrawView`:

- Shows confirmation information.
- Marks the book inactive.
- Cancels active reservations.
- Leaves current loans untouched.

`BookRestoreView`:

- POST-only.
- Marks the book active again.
- Refreshes queue state.

`CategoryManageListView`:

- Lists categories with total book count and active/lendable book count.

`CategoryCreateView` and `CategoryUpdateView`:

- Add and edit subject headings.

> Comment: The librarian views reuse public catalogue behavior where it makes sense, but they stay behind librarian permissions. That keeps the code consistent without opening management tools to students.

### Catalog URLs

Mounted under `/books/`:

- `/books/`
- `/books/<pk>/`
- `/books/category/<slug>/`
- `/books/manage/`
- `/books/manage/add/`
- `/books/manage/<pk>/edit/`
- `/books/manage/<pk>/withdraw/`
- `/books/manage/<pk>/restore/`
- `/books/manage/categories/`
- `/books/manage/categories/add/`
- `/books/manage/categories/<pk>/edit/`

The root URL `/catalog/` redirects permanently to `/books/`.

> Comment: `/books/` is the main catalogue address. The `/catalog/` redirect is helpful for anyone who guesses the older or more generic name.

## 6.3 Circulation App

The circulation app handles all actions where books change state: borrowing, returning, renewing, reserving, cancelling reservations, fines, and audit records.

The design principle is important: views do not implement borrowing rules directly. They call functions in `circulation/services.py`. This keeps the business rules consistent across views, tests, admin hooks, and future commands.

> Comment: This is one of the strongest parts of the project design. Business rules live in one service layer, so the project does not end up with different borrowing logic in different views.

### Policy Constants

Defined in `circulation/rules.py`:

- `LOAN_PERIOD_DAYS = 7`
- `MAX_ACTIVE_LOANS = 3`
- `MAX_RENEWALS = 1`
- `RENEWAL_PERIOD_DAYS = 7`
- `DUE_SOON_DAYS = 2`
- `FINE_PER_DAY = Decimal("100.00")`
- `RESERVATION_HOLD_DAYS = 3`
- `MAX_ACTIVE_RESERVATIONS = 3`

Date logic uses `timezone.localdate()` so due dates are based on the configured local timezone, `Africa/Lagos`, rather than UTC date boundaries.

> Comment: Using local dates matters because library fines are understood by calendar days, not by invisible UTC timing.

### BorrowRecord Model

Represents one loan of one book to one student.

Fields:

- `student`
- `book`
- `borrowed_date`
- `due_date`
- `returned_date`
- `renewal_count`
- `fine_amount`
- `fine_paid`

Important constraints:

- A student cannot have two active loans for the same book.
- Fine amount cannot be negative.
- A returned date cannot be earlier than the borrowed date.

Important properties:

- `is_returned`
- `is_overdue`
- `days_overdue`

Active loans are marked by `returned_date IS NULL`; there is no separate `is_returned` column.

> Comment: This avoids storing the same fact twice. A loan is active because it has no return date, which keeps the data clean.

### Reservation Model

Represents a student's queue position for an unavailable book.

Statuses:

- `waiting`
- `notified`
- `fulfilled`
- `expired`
- `cancelled`

Live reservation statuses:

- `waiting`
- `notified`

Fields:

- `student`
- `book`
- `reserved_date`
- `status`
- `notified_date`
- `expires_date`

Rules:

- One live reservation per student per book.
- Queue ordering is first-in, first-out by `reserved_date`.
- A notified reservation holds a returned copy until the expiry date.

Important methods/properties:

- `is_active`
- `has_expired`
- `queue_position()`

> Comment: The reservation model gives fairness to popular books. Students wait in the order they joined instead of racing to click at the right moment.

### AuditLog Model

Audit entries record important state-changing actions.

Actions include:

- borrow
- return
- renew
- reserve
- reservation cancellation
- fine paid
- book create
- book update
- book withdrawal
- book deletion
- role change

Fields:

- `user`
- `action`
- `target`
- `detail`
- `ip_address`
- `timestamp`

Important behavior:

- Audit logs are append-only.
- Saving an existing audit entry raises `ValueError`.
- The target is stored as text rather than a foreign key so the log remains meaningful even if the original record is later deleted.

> Comment: The audit log is written like a permanent record. It is meant to answer "who did what and when" even after the related object changes later.

### Circulation Services

Main service functions:

- `active_loans(student)`
- `active_reservations(student)`
- `borrow_book(student, book, request=None)`
- `return_book(record, actor=None, request=None)`
- `renew_loan(record, actor=None, request=None)`
- `reserve_book(student, book, request=None)`
- `cancel_reservation(reservation, actor=None, request=None)`
- `mark_fine_paid(record, actor=None, request=None)`
- `expire_lapsed_holds(book=None, request=None)`
- `offer_available_copies(book, request=None)`
- `refresh_queue(book, request=None)`
- `record_action(...)`

The services use database transactions and row locking with `select_for_update()` where appropriate. They update inventory counts with `F()` expressions so increments and decrements happen in the database instead of in stale Python objects.

> Comment: This protects the project from common inventory mistakes, especially two people trying to borrow the last available copy at almost the same time.

### Borrowing Workflow

When a student borrows a book:

1. The book row is locked and refreshed from the database.
2. Expired holds are cleared.
3. Available copies are offered to waiting reservations.
4. The service refuses the action if the book is withdrawn.
5. The service refuses the action if the student already has the book.
6. The service refuses the action if the student already has 3 active loans.
7. The service refuses the action if no copies are available.
8. The service refuses the action if available copies are held for other students.
9. The book's `available_quantity` is decremented.
10. A `BorrowRecord` is created with the default due date.
11. If the student had an active reservation for the book, it is marked fulfilled.
12. An audit log entry is written.

> Comment: The borrow workflow does more than create a loan. It also updates inventory, respects the queue, and leaves an audit trail.

### Returning Workflow

When a book is returned:

1. The book row is locked.
2. The loan row is locked.
3. Already-returned loans are refused.
4. Students can only return their own loans; librarians may process any loan.
5. `returned_date` is set.
6. Fine amount is calculated and stored.
7. The book's `available_quantity` is incremented.
8. An audit entry is written.
9. If a fine was charged, the student receives a notification.
10. The reservation queue is refreshed so the next waiting student may be notified.

> Comment: Returning a book can immediately affect another student, because a returned copy may be the one someone reserved.

### Renewal Workflow

A loan can be renewed only if:

- it has not already been returned,
- the actor is the borrower or a librarian,
- the renewal count is below the maximum,
- the loan is not overdue,
- no other student is waiting for the same book.

When renewed, the due date is extended from the existing due date, not from the current date.

> Comment: Extending from the existing due date is fair. A student who renews early does not lose the days they already had.

### Reservation Workflow

A student can reserve a book only when:

- the book is active,
- they do not already have it on loan,
- they do not already have a live reservation for it,
- no copy is freely available for them,
- they have fewer than 3 active reservations.

When a returned copy becomes available, the oldest waiting reservation is moved to `notified`, assigned a hold expiry date, and the student receives a notification.

> Comment: The hold expiry prevents one student from blocking the queue forever after being notified.

### Fine Workflow

Fine calculation:

```text
days late * 100.00 naira
```

Fines are calculated when the book is returned. A running overdue count can be shown while the loan is active, but the stored fine amount is fixed at return time.

Only librarians can mark fines as paid.

> Comment: The system calculates the fine, but payment confirmation stays with the librarian because that is a desk-level action.

### Circulation Exceptions

Every refusal is represented by a named exception. Examples:

- `BookNotAvailable`
- `BookWithdrawn`
- `AlreadyBorrowed`
- `LoanLimitReached`
- `CopiesHeldForOthers`
- `AlreadyReturned`
- `NotYourLoan`
- `RenewalLimitReached`
- `CannotRenewOverdue`
- `CannotRenewWithQueue`
- `CopiesAvailable`
- `AlreadyReserved`
- `ReservationLimitReached`
- `ReservationNotActive`
- `NotYourReservation`
- `NoFineOwed`
- `FineAlreadyPaid`

Views can catch the base `CirculationError` and show the message to the user, while tests can assert exact subclasses.

> Comment: Named exceptions make the code easier to test and easier to explain. Instead of only saying "something failed", the system can say exactly which rule stopped the action.

### Circulation URLs

Mounted under `/loans/`:

- `/loans/`
- `/loans/history/`
- `/loans/books/<pk>/borrow/`
- `/loans/books/<pk>/reserve/`
- `/loans/<pk>/renew/`
- `/loans/<pk>/return/`
- `/loans/reservations/<pk>/cancel/`
- `/loans/desk/`
- `/loans/desk/fines/`
- `/loans/desk/fines/<pk>/paid/`
- `/loans/desk/audit/`
- `/loans/audit/`

All state-changing circulation endpoints are POST-only.

> Comment: POST-only action URLs are important because borrowing, returning, renewing, and cancelling should never happen just because a browser or crawler followed a link.

## 6.4 Dashboard App

The dashboard app provides role-specific dashboard pages and persistent notifications.

> Comment: The dashboard is where each user lands after logging in, so it acts like the control center for the current role.

### Notification Model

Notification kinds:

- due soon
- overdue
- reserved copy ready
- reservation expired
- fine charged
- fine cleared
- general notice

Fields:

- `user`
- `kind`
- `message`
- `link`
- `is_read`
- `created_date`

Behavior:

- Notifications are ordered newest first.
- The unread count is indexed by user and read state.
- `mark_read()` updates only the `is_read` field.

> Comment: Notifications are stored in the database because some messages should survive beyond one page load or one browser session.

### Dashboard Views

`home(request)`:

- Requires login.
- Shows a librarian dashboard for librarians.
- Shows a student dashboard for students.
- Gets data from `dashboard/utils.py`.

`notifications_list(request)`:

- Requires login.
- Lists notifications for the current user.
- Supports `filter=all` and `filter=unread`.
- Paginates by 15.

`mark_notification_read(request, pk)`:

- Requires login and POST.
- Only marks notifications belonging to the current user.
- Redirects safely back to `next` when valid.

`mark_all_notifications_read(request)`:

- Requires login and POST.
- Marks all current user's unread notifications as read.

> Comment: The notification views always filter by the current user, which prevents one account from reading or changing another account's notifications.

### Dashboard URLs

Mounted under `/dashboard/`:

- `/dashboard/`
- `/dashboard/notifications/`
- `/dashboard/notifications/<pk>/read/`
- `/dashboard/notifications/read-all/`

> Comment: These URLs are intentionally small because dashboard actions are personal to the signed-in user.

## 7. Root URLs and Public Pages

Root URL patterns:

- `/admin/`
- `/`
- `/accounts/`
- `/books/`
- `/catalog/`
- `/loans/`
- `/dashboard/`
- `/settings/`
- `/privacy/`
- `/terms/`
- `/security/`

The home page is a public `TemplateView` using `templates/pages/home.html`.

The aliases `/settings/`, `/privacy/`, `/terms/`, and `/security/` redirect to their account-page equivalents.

> Comment: The root routes make the site easier to navigate. A user can type common addresses like `/settings/` without needing to remember the full account path.

## 8. Permissions and Access Control

The project uses several layers of access control:

> Comment: Permissions are handled in layers because not every rule is the same kind of rule. Some depend on login state, some depend on role, and some depend on who owns a specific record.

### Site-Wide Login Requirement

`LoginRequiredMiddleware` makes login required by default. Public pages are explicitly exempted with `login_not_required`.

Public pages include:

- landing page
- catalogue list
- category pages
- book detail pages
- registration
- login
- password reset request flow

> Comment: Requiring login by default is safer than protecting pages one by one. If a developer forgets to mark a new page public, it stays private.

### Role-Based Access

Student-only behavior:

- borrowing
- reserving
- reviewing books

Librarian-only behavior:

- adding/editing/withdrawing/restoring books
- managing categories
- viewing student directory
- loan desk
- fine management
- audit log

The codebase contains role decorators and mixins in `accounts/decorators.py` and `accounts/mixins.py`.

> Comment: The role checks are written as reusable helpers, which keeps the views cleaner and reduces repeated permission code.

### Ownership Checks

Some permissions cannot be decided by role alone. For example, a student may only renew or return their own loan. These checks happen inside service functions because services can inspect the exact row being changed.

> Comment: This is an important distinction. A student role can tell us the user is allowed to borrow generally, but it cannot tell us that a specific loan belongs to them.

## 9. Database Design Summary

Major tables:

- `accounts_user`
- `accounts_usersettings`
- `accounts_systemconfig`
- `catalog_category`
- `catalog_book`
- `catalog_review`
- `circulation_borrowrecord`
- `circulation_reservation`
- `circulation_auditlog`
- `dashboard_notification`

> Comment: The database design follows the main app boundaries. Each app owns the tables that match its responsibility.

Important relationships:

- A user has many borrow records.
- A user has many reservations.
- A user has many reviews.
- A user has many notifications.
- A user has one settings row.
- A category has many books.
- A book has many reviews.
- A book has many borrow records.
- A book has many reservations.

Important integrity rules:

- A category with books cannot be deleted.
- A book/student with loan history is protected from deletion through borrow records.
- A student cannot hold two active loans for the same book.
- A student cannot hold two live reservations for the same book.
- A student cannot review the same book twice.
- Ratings must be 1 to 5.
- Available copies cannot exceed total copies.
- Fine amount cannot be negative.
- Audit log entries cannot be edited.

> Comment: Many of these rules are enforced at the database level, not only in forms. That makes the project more reliable if data is changed through tests, admin tools, or future scripts.

## 10. Main User Workflows

> Comment: This section explains the project from the user's point of view. It is useful when demonstrating the system because it follows what people actually do on the site.

### Student Registration

1. Visitor opens `/accounts/register/`.
2. Registration form validates account details.
3. A new user is created with role `student`.
4. The user is logged in immediately.
5. The user is redirected to the dashboard.

> Comment: Logging the student in immediately makes registration feel complete. The user does not have to type the same password again right after creating the account.

### Student Login

1. Visitor opens `/accounts/login/`.
2. Rate limits are checked by IP and username.
3. Authentication form validates credentials.
4. User is redirected to the dashboard.

### Browse and Search Books

1. Visitor opens `/books/`.
2. The system loads active books only.
3. Visitor may search by title, author, or ISBN.
4. Visitor may filter by category.
5. Visitor may sort by newest, title, author, rating, or popularity.
6. Results are paginated.

> Comment: The catalogue is public because discovery should not require an account. Borrowing is where authentication becomes necessary.

### Review a Book

1. Student opens a book detail page.
2. If signed in as a student, the review form is displayed.
3. Student submits rating and optional comment.
4. Existing review is edited if one exists.
5. Otherwise a new review is created.

### Borrow a Book

1. Student clicks borrow on a book.
2. View calls `borrow_book()`.
3. Service enforces active book, availability, loan limit, duplicate-loan rule, and reservation holds.
4. Inventory is decremented.
5. Loan is created.
6. Audit log is written.

> Comment: The audit entry is useful for accountability. If a question comes up later, the system has a record of the action.

### Reserve a Book

1. Student clicks reserve when no copy is free for them.
2. View calls `reserve_book()`.
3. Service checks active status, active loans, duplicate reservations, free copies, and reservation limit.
4. Reservation is created.
5. Audit log is written.

> Comment: Reservation is only useful when the system also protects the copy once it becomes available. That is why borrowing checks whether copies are being held for other students.

### Return a Book

1. Student or librarian posts to the return endpoint.
2. Service locks loan and book rows.
3. Service checks ownership and return state.
4. Return timestamp and fine amount are saved.
5. Inventory is incremented.
6. Notifications and audit log are written.
7. Queue is refreshed.

> Comment: The return workflow connects several parts of the system: inventory, fines, notifications, audit logs, and reservations.

### Renew a Loan

1. Student or librarian posts to the renewal endpoint.
2. Service checks return state, ownership, renewal cap, overdue state, and reservation queue.
3. Due date is extended.
4. Renewal count is incremented.
5. Audit log is written.

### Librarian Adds a Book

1. Librarian opens `/books/manage/add/`.
2. Book form validates input and normalizes ISBN.
3. Available copies are set equal to total quantity.
4. Book is saved.

### Librarian Withdraws a Book

1. Librarian opens the withdraw confirmation page.
2. Page shows copies on loan and active reservations.
3. On POST, book is marked inactive.
4. Active reservations are cancelled.
5. Current loans continue until return.

> Comment: This is a realistic policy. Withdrawing a book stops future borrowing but does not pretend existing loans never happened.

### Librarian Marks a Fine Paid

1. Librarian opens the fine desk.
2. Librarian posts to the paid endpoint.
3. Service checks that a fine exists and is unpaid.
4. Fine is marked paid.
5. Audit log and notification are created.

## 11. Security Design

Important security choices:

- Login required by default across the whole site.
- Public pages must explicitly opt out.
- Role checks are centralized in decorators/mixins and user properties.
- Ownership checks are done in circulation services.
- POST-only endpoints for state changes.
- CSRF protection is enabled.
- Passwords use Argon2 first.
- Password validators reject weak passwords.
- Login, registration, password reset, borrow, and reserve flows use rate limiting.
- Sort input is whitelisted.
- Review book/student values are supplied server-side, not through hidden fields.
- Audit logs are append-only.
- Production mode enables HTTPS redirect, secure cookies, HSTS, and proxy SSL support.
- Content Security Policy limits script, style, image, font, object, form, frame, and base URI sources.

> Comment: The security decisions are mostly defensive defaults. The project tries to make the safe behavior the normal behavior.

## 12. Deployment Notes

The project includes a `Procfile`, suggesting deployment to a platform such as Railway, Heroku, or a similar process-based host.

> Comment: The project is prepared for deployment, but production needs careful environment variables and persistent storage. Running locally and running online are not exactly the same.

Before deployment:

1. Set `DEBUG=False`.
2. Set a strong `SECRET_KEY`.
3. Set `ALLOWED_HOSTS`.
4. Set `CSRF_TRUSTED_ORIGINS` for HTTPS deployment origins.
5. Set `DATABASE_URL` to a production database.
6. Use PostgreSQL for production.
7. Configure a production cache such as Redis or Memcached for rate limiting.
8. Run migrations.
9. Run `collectstatic`.
10. Ensure uploaded media storage is persistent.

Useful commands:

```powershell
python manage.py check
python manage.py migrate
python manage.py collectstatic
python manage.py createsuperuser
```

Production warning:

The local memory cache is acceptable for development but not for production rate limiting. With multiple workers, each process would maintain its own counters. The settings intentionally allow Django/system checks to complain in production until this is replaced.

> Comment: This warning matters because rate limiting looks like it works locally, but local memory caching is not reliable when the app is scaled across processes.

## 13. Testing

The project contains test files:

- `accounts/tests.py`
- `catalog/tests.py`
- `circulation/tests.py`
- `dashboard/tests.py`

> Comment: Tests are especially important in this project because circulation rules involve money, availability, and user permissions.

The project also includes `pytest.ini`, but tests may also be runnable through Django's built-in runner depending on the configured test style.

Common commands:

```powershell
python manage.py test
```

If pytest and pytest-django are installed:

```powershell
pytest
```

Recommended test focus:

- registration creates student accounts
- superuser creation creates librarian role
- public catalogue hides withdrawn books
- librarian catalogue shows withdrawn books
- ISBN normalization and validation
- duplicate review prevention
- loan limit enforcement
- duplicate active loan prevention
- unavailable book borrowing refusal
- reservation queue behavior
- renewal restrictions
- fine calculation
- audit log immutability
- notification read/unread behavior
- permission checks for student vs librarian pages

> Comment: These tests should focus on behavior, not only page loading. The most important question is whether the system refuses the wrong action and accepts the right one.

## 14. Maintenance Notes

> Comment: This section is for the next developer or the future version of this project. It explains where to make changes without accidentally breaking related behavior.

### Changing Loan Rules

Most live circulation rules are constants in `circulation/rules.py`.

Change these when policy changes:

- `LOAN_PERIOD_DAYS`
- `MAX_ACTIVE_LOANS`
- `MAX_RENEWALS`
- `RENEWAL_PERIOD_DAYS`
- `FINE_PER_DAY`
- `RESERVATION_HOLD_DAYS`
- `MAX_ACTIVE_RESERVATIONS`

After changing them, update tests and any user-facing documentation.

> Comment: Loan policy is easy to change in one file, but every visible explanation and test expectation should move with it.

### Adding a Book Field

If a field is added to `Book`, update:

- `catalog/models.py`
- migrations
- `catalog/forms.py` if librarians should edit it
- templates that display book data
- tests
- this documentation

`BookForm` uses an explicit `fields` list, so new model fields do not automatically appear on the form.

> Comment: This is intentional. New data should not suddenly appear on a librarian's form without someone deciding how it should be used.

### Changing Roles

If new roles are added:

- update `User.Role`
- update role properties
- update decorators/mixins
- update dashboard routing
- update templates and tests
- review every use of `is_student` and `is_librarian`

### Updating Audit Actions

If a new important state-changing action is introduced:

- add a value to `AuditAction`
- create audit entries through `record_action()`
- add tests that prove the action is recorded
- decide whether the action should appear in librarian audit views

### Uploaded Digital Files

Digital files are stored under `book_digital/` inside `MEDIA_ROOT`. Cover images are stored under `book_covers/`.

In local development this is fine. In production, ensure `MEDIA_ROOT` points at persistent storage. If the deployment platform has an ephemeral filesystem, uploads may disappear unless external storage is configured.

> Comment: Upload handling is one of the first things to check before real deployment. A book cover or PDF should not vanish when the server restarts.

## 15. Known Gaps and Improvement Ideas

These are not necessarily bugs, but they are useful future improvements:

- Connect `SystemConfig` to circulation rules so librarians can change policy from the database instead of editing constants.
- Replace local memory cache with Redis or Memcached in production.
- Add real email backend settings for production password reset and notices.
- Implement real MFA if `mfa_enabled` is intended to become functional.
- Add an API layer if `api_access_enabled`, `api_key_primary`, and `webhook_url` are meant to be active integrations.
- Update the digital file validation message to mention `.mobi` if MOBI support is intentional.
- Add scheduled or management-command support for due-soon and overdue notification sweeps.
- Add object-level tests around withdrawn book restoration and reservation cancellation side effects.
- Add documentation screenshots if this is for a final school/project report.

> Comment: These points are honest project notes. They show what already works and what would make the system stronger in a future version.

## 16. Quick Reference

Main local commands:

```powershell
cd athenaeum_ikedi
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_library
python manage.py runserver
```

Main local URLs:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/books/
http://127.0.0.1:8000/accounts/login/
http://127.0.0.1:8000/accounts/register/
http://127.0.0.1:8000/dashboard/
http://127.0.0.1:8000/loans/
http://127.0.0.1:8000/admin/
```

Key admin/librarian URLs:

```text
/books/manage/
/books/manage/add/
/books/manage/categories/
/loans/desk/
/loans/desk/fines/
/loans/desk/audit/
/accounts/manage/students/
```

Key project files:

```text
config/settings.py
config/urls.py
accounts/models.py
catalog/models.py
catalog/views.py
catalog/manage_views.py
circulation/models.py
circulation/rules.py
circulation/services.py
dashboard/models.py
dashboard/views.py
```

> Comment: This final section is meant for quick use when someone just wants to run or inspect the project without reading the entire documentation again.
