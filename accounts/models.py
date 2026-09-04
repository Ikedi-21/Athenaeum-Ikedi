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
