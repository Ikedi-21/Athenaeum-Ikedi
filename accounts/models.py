"""
The user model for Athenaeum Ikedi.

Django's built in User class is replaced here rather than paired with a
separate profile table. That way a role check needs no join, and no
signal has to keep a second row in step with the first.
"""

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
        # The first value in each pair is what the database stores, the
        # second is the label shown to a human.
        STUDENT = "student", "Student"
        LIBRARIAN = "librarian", "Librarian"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        # Every new account is a student. Defaulting the other way would
        # mean a single forgotten field hands out librarian powers, so the
        # safe value is the default and promotion is deliberate.
        default=Role.STUDENT,
        help_text="Students borrow books. Librarians manage the catalogue.",
    )

    # AbstractUser leaves email optional and allows duplicates. A library
    # needs a reliable way to reach a borrower about an overdue book, and
    # password reset only works if an address identifies one account, so
    # it is required and unique here.
    email = models.EmailField(unique=True)

    # Attach the manager defined above so createsuperuser behaves.
    objects = LibraryUserManager()

    class Meta:
        # Alphabetical by default, which is what the librarian's list of
        # students should look like without every view having to say so.
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

        Exists so that no view, decorator or template ever compares the
        raw string "student". If the stored values ever change, they
        change in one place.
        """
        return self.role == self.Role.STUDENT

    @property
    def is_librarian(self):
        """
        True for staff who manage the catalogue and process returns.

        Deliberately does not treat is_superuser as an automatic yes. The
        manager above already gives every superuser the librarian role,
        so the two cannot drift apart, and keeping this check to the role
        field alone means is_student and is_librarian stay mutually
        exclusive, which is what the business rule tests rely on.
        """
        return self.role == self.Role.LIBRARIAN

    @property
    def user_settings(self):
        """
        Returns the UserSettings instance for this user, creating one with defaults if needed.
        """
        settings_obj, _ = UserSettings.objects.get_or_create(user=self)
        return settings_obj


class UserSettings(models.Model):
    """
    Individual user profile and configuration preferences.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="settings"
    )
    bio = models.TextField(blank=True, max_length=500, default="")
    phone_number = models.CharField(max_length=20, blank=True, default="")

    # Notification preferences
    notify_email_loans = models.BooleanField(
        default=True,
        help_text="Receive email confirmation upon checkout and renewal."
    )
    notify_email_overdue = models.BooleanField(
        default=True,
        help_text="Receive urgent alerts when borrowed titles approach due dates."
    )
    notify_email_digest = models.CharField(
        max_length=10,
        choices=[("none", "None"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="daily",
        help_text="Summary email frequency for library activities and holds."
    )

    # Display & Localization
    theme = models.CharField(
        max_length=10,
        choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
        default="light",
    )
    timezone = models.CharField(max_length=50, default="Africa/Lagos")
    date_format = models.CharField(
        max_length=20,
        choices=[
            ("YYYY-MM-DD", "YYYY-MM-DD (ISO)"),
            ("DD/MM/YYYY", "DD/MM/YYYY (UK)"),
            ("MM/DD/YYYY", "MM/DD/YYYY (US)"),
        ],
        default="YYYY-MM-DD",
    )

    # Security & Access
    mfa_enabled = models.BooleanField(
        default=False,
        help_text="Two-factor authentication requirement status."
    )

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings for {self.user.username}"


class SystemConfig(models.Model):
    """
    Enterprise platform configuration parameters managed by Librarians/Admins.
    Implements a database-backed singleton pattern.
    """
    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    # Circulation & Policy Rules
    loan_duration_days = models.PositiveIntegerField(
        default=14,
        help_text="Standard loan window granted for borrowed titles in days."
    )
    max_books_per_student = models.PositiveIntegerField(
        default=3,
        help_text="Maximum simultaneous active loans permitted per student account."
    )
    fine_rate_per_day = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=50.00,
        help_text="Overdue fine penalty accrued per calendar day late in Naira (₦)."
    )
    allow_student_reservations = models.BooleanField(
        default=True,
        help_text="Enable self-service queue holds on checked-out books."
    )
    maintenance_mode = models.BooleanField(
        default=False,
        help_text="Suspend public transactions for scheduled maintenance operations."
    )
    session_timeout_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Idle session inactivity duration before re-authentication is enforced."
    )

    # API & Integration Parameters
    api_access_enabled = models.BooleanField(
        default=True,
        help_text="Enable authenticated REST API access for external institutional systems."
    )
    api_key_primary = models.CharField(
        max_length=64,
        default="ath_live_8f93e2b10a9c4d7e8b9101112",
        help_text="Primary institutional bearer token."
    )
    webhook_url = models.URLField(
        blank=True,
        default="https://api.athenaeum.edu/webhooks/circulation",
        help_text="Endpoint receiving automated webhook event payloads."
    )

    # Enterprise Resource Limits & Subscription
    subscription_tier = models.CharField(
        max_length=50,
        default="Enterprise Academic Pro",
        help_text="Active institution license subscription tier."
    )
    storage_allocated_gb = models.PositiveIntegerField(
        default=50,
        help_text="Total cloud storage quota allocated in Gigabytes."
    )
    storage_used_gb = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=6.85,
        help_text="Current storage consumption in Gigabytes."
    )
    max_active_members = models.PositiveIntegerField(
        default=5000,
        help_text="Contracted member account threshold."
    )

    class Meta:
        verbose_name = "Enterprise System Configuration"
        verbose_name_plural = "Enterprise System Configuration"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj

    def __str__(self):
        return f"SystemConfig ({self.subscription_tier})"
