"""
Django settings for Athenaeum Ikedi.

Anything secret, or anything that differs between this machine and a
server, is read from a .env file at the project root by python-decouple.
See .env.example for the keys this file expects to find.

Django 6.1 already defaults to HttpOnly session cookies, SameSite=Lax,
X-Frame-Options DENY, content type nosniff and a same-origin referrer
policy, so none of those are repeated below. This file states only what
differs from the framework defaults.
"""

from pathlib import Path

from decouple import Csv, config
from django.utils.csp import CSP

# BASE_DIR is the folder holding manage.py. Every other path is built
# from it, so the project behaves identically no matter which directory
# it is launched from.
BASE_DIR = Path(__file__).resolve().parent.parent


# =====================================================================
# Environment and secrets
# =====================================================================

# Signs sessions, password reset links and CSRF tokens. No default is
# given on purpose: if .env is missing the project should refuse to
# start rather than quietly run on a predictable key.
SECRET_KEY = config("SECRET_KEY")

# True only on a development machine. This also gates the hardening
# block at the bottom of the file, so it defaults to False. An unset
# DEBUG should mean "assume this is a server".
DEBUG = config("DEBUG", default=False, cast=bool)

# Hostnames this site answers to. Csv() splits the comma separated
# string from .env into a Python list.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())


# =====================================================================
# Applications
# =====================================================================

INSTALLED_APPS = [
    # Django's own apps.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party. django_ratelimit is listed only so that its own system
    # check runs: the @ratelimit decorator itself works without it. The
    # check refuses a cache backend that cannot count reliably, which is
    # worth having, because a rate limit built on the wrong cache fails
    # silently rather than loudly.
    "django_ratelimit",
    # Our four apps. accounts is first because it defines the user model
    # the other three depend on.
    "accounts",
    "catalog",
    "circulation",
    "dashboard",
]

# Use our own user class instead of Django's built in one. This must be
# set before the first migrate ever runs, which is why it is here before
# anything else touches the database.
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    # Applies the HTTPS, HSTS and nosniff response headers.
    "django.middleware.security.SecurityMiddleware",
    # Attaches the Content Security Policy header defined further down.
    # Response middleware runs bottom upward, so sitting high in this
    # list means the header lands on responses from everything below it.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Rejects any POST arriving without a valid CSRF token.
    "django.middleware.csrf.CsrfViewMiddleware",
    # Puts request.user in place, so it must follow SessionMiddleware.
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Makes a login the default requirement for every view in the project
    # instead of something each view has to remember to ask for. A view
    # that should be public opts out with the login_not_required
    # decorator, so forgetting to protect a page now leaves it locked
    # rather than open. It has to sit after AuthenticationMiddleware
    # because the check it performs reads request.user.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    # Keeps the request in a context variable for the length of the view, so
    # that the audit log can name the person who changed a book in the admin
    # site. Django hands a signal receiver the row and nothing else, and
    # this is the only thing that closes that gap. It sits below
    # AuthenticationMiddleware because the whole point is to reach
    # request.user, which does not exist until that has run.
    "circulation.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Refuses to be embedded in a frame on another site, which blocks
    # clickjacking.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # One shared templates folder at the project root rather than one
        # per app, because base.html and dashboard_base.html are extended
        # by all four apps.
        "DIRS": [BASE_DIR / "templates"],
        # Still True, so Django's own admin templates are still found.
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Supplies the csp_nonce variable. Any inline script or
                # style block we write must carry nonce="{{ csp_nonce }}"
                # or the browser refuses to run it, which is exactly the
                # protection wanted: injected script cannot guess it.
                "django.template.context_processors.csp",
                "dashboard.context_processors.notification_context",
                "dashboard.context_processors.theme_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# =====================================================================
# Database
# =====================================================================

# SQLite, as the assignment specifies. Moving to PostgreSQL later is a
# change to this block alone.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # Wait up to 20 seconds for a competing write instead of
            # raising "database is locked" straight away. SQLite permits
            # only one writer at a time, and borrowing a book writes to
            # two tables inside a single transaction.
            "timeout": 20,
        },
    }
}

# Primary key type for any model that does not declare its own.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =====================================================================
# Cache
# =====================================================================

# django-ratelimit keeps its counters in the cache, so a working cache is
# what makes the login and borrow limits function at all. Local memory is
# fine for development. On a real server this must become Redis or
# Memcached, because local memory is per process and each worker would
# otherwise keep its own separate count, multiplying every limit by the
# number of workers.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "athenaeum-cache",
    }
}

# django-ratelimit raises its own system check, E003, against any cache it
# considers unsafe to count in, and local memory is on that list for the
# reason given above. The check is correct, so it is not removed: it is
# silenced only while DEBUG is True. On a server, where DEBUG is False,
# the check fires again and manage.py check refuses to pass until the
# cache above has been swapped for Redis or Memcached, which turns a
# quiet weakness into a blocking error at exactly the moment it starts to
# matter. W001 is the same check's softer warning about any backend it
# does not recognise, and is silenced alongside it for the same window.
if DEBUG:
    SILENCED_SYSTEM_CHECKS = [
        "django_ratelimit.E003",
        "django_ratelimit.W001",
    ]


# =====================================================================
# Authentication
# =====================================================================

# Argon2 is deliberately first. Django's default order puts PBKDF2 first,
# and PBKDF2 is not broken, but Argon2 is memory hard, which makes it far
# more expensive to attack with GPU hardware. The older algorithms stay
# in the list so an existing hash can still be verified, and Django then
# transparently re-hashes that password with Argon2 on the next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        # Rejects a password too similar to the username or email.
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        # Raised from Django's default of 8. Length is the single largest
        # factor in how long a password takes to crack.
        "OPTIONS": {"min_length": 10},
    },
    {
        # Checks against a bundled list of 20,000 common passwords.
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        # Rejects entirely numeric passwords.
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Where @login_required sends anonymous visitors, and where people land
# after logging in or out. These are URL pattern names, so they resolve
# only once the relevant app defines them.
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "catalog:book_list"

# Tightened from Django's two week default, and combined with
# SESSION_SAVE_EVERY_REQUEST it becomes a rolling window: one week of
# inactivity ends the session, but active use keeps extending it. The
# cost is one extra session write per request, negligible at this scale.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
SESSION_SAVE_EVERY_REQUEST = True


# =====================================================================
# Internationalisation
# =====================================================================

LANGUAGE_CODE = "en-us"

# Local time zone, used for display and for deciding whether a loan is
# overdue. Timestamps are still stored in UTC because USE_TZ is True.
TIME_ZONE = "Africa/Lagos"

USE_I18N = True

USE_TZ = True


# =====================================================================
# Email
# =====================================================================

# Django 6.1 configures email through MAILERS rather than the older
# EMAIL_BACKEND setting. The console backend prints messages to the
# terminal instead of sending them, which is what makes the password
# reset flow testable locally without an SMTP server.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# =====================================================================
# Static files and uploads
# =====================================================================

# URL prefix that CSS, JS and logo files are served under.
STATIC_URL = "static/"

# Our own static files, the ones written by hand and committed.
STATICFILES_DIRS = [BASE_DIR / "static"]

# Where collectstatic gathers everything for a real web server to serve.
# Generated output, so it is gitignored.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Book cover uploads. Kept apart from static/ because this is user
# supplied data, not source. Size and file type limits on covers are
# enforced in the book form's validation rather than here, because
# FILE_UPLOAD_MAX_MEMORY_SIZE is only the threshold at which an upload
# spills to a temporary file, not a rejection limit.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# =====================================================================
# Content Security Policy
# =====================================================================

# CSP tells the browser which sources it may load code from, so a script
# injected through a review comment or a book title will not execute even
# if it reaches the page. Django 6 ships this natively, which is why
# django-csp is absent from requirements.txt.
#
# CSP.NONCE is swapped for a fresh random value on every response and
# exposed to templates as csp_nonce.
SECURE_CSP = {
    # Fallback for any directive not named below.
    "default-src": [CSP.SELF],
    # Our own JS files, plus inline scripts carrying the nonce.
    "script-src": [CSP.SELF, CSP.NONCE],
    # Our own stylesheets, plus nonce bearing <style> blocks.
    "style-src": [CSP.SELF, CSP.NONCE],
    # A nonce cannot be attached to a style="..." attribute, and
    # style-src would otherwise block those too. Allowing them keeps
    # things like a star rating width or a chart container height
    # workable, while <style> blocks still require the nonce.
    "style-src-attr": [CSP.UNSAFE_INLINE],
    # Covers served from our media folder, and data: for inline SVG.
    "img-src": [CSP.SELF, "data:"],
    # Fonts come from our static folder, not a CDN.
    "font-src": [CSP.SELF],
    # No plugins, no embedded objects.
    "object-src": [CSP.NONE],
    # Forms may only submit back to this site.
    "form-action": [CSP.SELF],
    # Nobody may place this site inside an iframe.
    "frame-ancestors": [CSP.NONE],
    # Stops an injected <base> tag from repointing every relative URL on
    # the page at an attacker's server.
    "base-uri": [CSP.SELF],
}

# SECURE_CSP_REPORT_ONLY takes the same shape and logs violations without
# blocking them, which is the way to test a stricter policy against a
# working site before enforcing it.

# =====================================================================
# Production hardening
# =====================================================================

# Everything below is either pointless or actively obstructive on a local
# http://127.0.0.1 machine, so it switches on only when DEBUG is False.
# That means there is nothing to remember at deploy time: set DEBUG=False
# in the server's .env and the hardening arrives with it.
if not DEBUG:
    # Redirect any http:// request to https://.
    SECURE_SSL_REDIRECT = True

    # Instruct browsers to refuse plain http for this domain for a year,
    # so the redirect above cannot be intercepted on a repeat visit. Only
    # safe once HTTPS is confirmed working, because it is hard to undo.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Never transmit the session or CSRF cookie over plain http.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Behind a reverse proxy such as nginx, Django sees plain http on the
    # internal hop and the redirect above would loop forever. This header
    # tells it the original request was https. Only correct if the proxy
    # always sets the header itself, otherwise a client could forge it.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

