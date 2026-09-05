"""
Dashboard models.

Only one model lives here, the in app notification. The analytics the
librarian dashboard shows are all derived by querying the other apps, so
there is nothing to store for them. Those queries will live in utils.py.
"""

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    A short message shown to one user inside the site.

    Kept separate from Django's messages framework on purpose. A framework
    message is written into the session and disappears the moment it is
    displayed once, which is right for "book borrowed successfully" and
    wrong for "your reserved copy is ready", because that one has to
    survive logging out and still be there tomorrow.
    """

    class Kind(models.TextChoices):
        """
        What the notification is about.

        Stored so the navbar can show a different icon or colour per kind
        without parsing the message text, and so a query can count only
        the overdue warnings.
        """

        DUE_SOON = "due_soon", "Due soon"
        OVERDUE = "overdue", "Overdue"
        RESERVATION_READY = "reservation_ready", "Reserved copy ready"
        RESERVATION_EXPIRED = "reservation_expired", "Reservation expired"
        FINE_CHARGED = "fine_charged", "Fine charged"
        FINE_CLEARED = "fine_cleared", "Fine cleared"
        GENERAL = "general", "Notice"

    # CASCADE, because a notification is meaningless without the person it
    # was addressed to. Nothing here is a record worth preserving.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    kind = models.CharField(
        max_length=32,
        choices=Kind.choices,
        default=Kind.GENERAL,
    )

    # A single line, so the dropdown in the navbar has a predictable
    # height. Anything longer belongs on the page the link points at.
    message = models.CharField(max_length=255)

    # An internal path such as /circulation/loans/, so clicking the
    # notification lands on the page it is about. A plain CharField rather
    # than a URLField because a URLField insists on a scheme and host,
    # which an internal path does not have. Blank when there is nowhere
    # useful to go.
    link = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional path within the site, for example /my-loans/.",
    )

    is_read = models.BooleanField(default=False)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first, which is what a notification list wants.
        ordering = ["-created_date"]

        indexes = [
            # The unread count in the navbar runs on every single page
            # load, filtering on user and is_read together. This index is
            # what keeps that query from touching every notification row
            # in the table as the site fills up.
            models.Index(
                fields=["user", "is_read"],
                name="notification_by_user_state",
            ),
        ]

    def __str__(self):
        """Shown in the admin list."""
        state = "read" if self.is_read else "unread"
        return f"{self.user}: {self.message} ({state})"

    def mark_read(self):
        """
        Mark this notification as seen.

        update_fields limits the UPDATE statement to the one column that
        changed, instead of rewriting every column. That avoids the case
        where two requests save the same stale object and one silently
        undoes the other's change to a different field.
        """
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])
