"""
The user model and configuration entities for Athenaeum Ikedi.

Django's built in User class is replaced here rather than paired with a
separate profile table. That way a role check needs no join, and no
signal has to keep a second row in step with the first.
"""

from decimal import Decimal
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class LibraryUserManager(UserManager):
    """
    Standard Django user manager with one change, described below.
    """

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """
        Force the librarian role on any superuser created from the
        command line.

        Without this, createsuperuser would produce an account holding
        the default student role, and our own librarian_required
        decorator would then refuse it entry to the very pages it was
        created to manage. setdefault is used rather than a plain
        assignment so an explicit role passed by a caller still wins.
        """
        extra_fields.setdefault("role", User.Role.LIBRARIAN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    A library member: either a student who borrows books, or a librarian
    who manages the catalogue.
    """

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        LIBRARIAN = "librarian", "Librarian"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
        help_text="Students borrow books. Librarians manage the catalogue.",
    )

    email = models.EmailField(unique=True)

    objects = LibraryUserManager()

    class Meta:
        ordering = ["username"]

    def __str__(self):
        """
        Shown in the admin, in form dropdowns, and anywhere a user object
        is printed. Falls back to the username when no name was given.
        """
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def is_student(self):
        """
        True for a borrower.
        """
        return self.role == self.Role.STUDENT

    @property
    def is_librarian(self):
        """
        True for staff who manage the catalogue and process returns.
        Superusers are also librarians by manager default.
        """
        return self.role == self.Role.LIBRARIAN

    @property
    def user_settings(self):
        """
        Always returns the associated UserSettings record, auto-creating it if needed.
        """
        obj, _ = UserSettings.objects.get_or_create(user=self)
        return obj


class SystemConfig(models.Model):
    """
    Singleton model for enterprise system configuration and circulation policies.
    """

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False
    )
    loan_duration_days = models.PositiveIntegerField(
        default=14,
        help_text="Standard loan window granted for borrowed titles in days.",
    )
    max_books_per_student = models.PositiveIntegerField(
        default=3,
        help_text="Maximum simultaneous active loans permitted per student account.",
    )
    fine_rate_per_day = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Overdue fine penalty accrued per calendar day late in Naira (₦).",
    )
    allow_student_reservations = models.BooleanField(
        default=True,
        help_text="Enable self-service queue holds on checked-out books.",
    )
    maintenance_mode = models.BooleanField(
        default=False,
        help_text="Suspend public transactions for scheduled maintenance operations.",
    )
    session_timeout_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Idle session inactivity duration before re-authentication is enforced.",
    )
    api_access_enabled = models.BooleanField(
        default=True,
        help_text="Enable authenticated REST API access for external institutional systems.",
    )
    api_key_primary = models.CharField(
        max_length=64,
        default="ath_live_8f93e2b10a9c4d7e8b9101112",
        help_text="Primary institutional bearer token.",
    )
    webhook_url = models.URLField(
        blank=True,
        default="https://api.athenaeum.edu/webhooks/circulation",
        help_text="Endpoint receiving automated webhook event payloads.",
    )
    subscription_tier = models.CharField(
        max_length=50,
        default="Enterprise Academic Pro",
        help_text="Active institution license subscription tier.",
    )
    storage_allocated_gb = models.PositiveIntegerField(
        default=50,
        help_text="Total cloud storage quota allocated in Gigabytes.",
    )
    storage_used_gb = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("6.85"),
        help_text="Current storage consumption in Gigabytes.",
    )
    max_active_members = models.PositiveIntegerField(
        default=5000,
        help_text="Contracted member account threshold.",
    )

    class Meta:
        verbose_name = "Enterprise System Configuration"
        verbose_name_plural = "Enterprise System Configuration"

    def __str__(self):
        return "System Configuration"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)


class UserSettings(models.Model):
    """
    Per-user personalization preferences and communication controls.
    """

    class ThemeChoices(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        SYSTEM = "system", "System"

    class DigestFrequency(models.TextChoices):
        NONE = "none", "None"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    class DateFormatChoices(models.TextChoices):
        ISO = "YYYY-MM-DD", "YYYY-MM-DD (ISO)"
        UK = "DD/MM/YYYY", "DD/MM/YYYY (UK)"
        US = "MM/DD/YYYY", "MM/DD/YYYY (US)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    bio = models.TextField(max_length=500, blank=True, default="")
    phone_number = models.CharField(max_length=20, blank=True, default="")
    notify_email_loans = models.BooleanField(
        default=True,
        help_text="Receive email confirmation upon checkout and renewal.",
    )
    notify_email_overdue = models.BooleanField(
        default=True,
        help_text="Receive urgent alerts when borrowed titles approach due dates.",
    )
    notify_email_digest = models.CharField(
        max_length=10,
        choices=DigestFrequency.choices,
        default=DigestFrequency.DAILY,
        help_text="Summary email frequency for library activities and holds.",
    )
    theme = models.CharField(
        max_length=10,
        choices=ThemeChoices.choices,
        default=ThemeChoices.LIGHT,
    )
    timezone = models.CharField(max_length=50, default="Africa/Lagos")
    date_format = models.CharField(
        max_length=20,
        choices=DateFormatChoices.choices,
        default=DateFormatChoices.ISO,
    )
    mfa_enabled = models.BooleanField(
        default=False,
        help_text="Two-factor authentication requirement status.",
    )

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings for {self.user.username}"
