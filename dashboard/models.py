"""
Models for the dashboard app: user notifications and alert dispatch.
"""

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    An in-app alert for a student or librarian regarding loan due dates,
    queue updates, holds, or fines.
    """

    class Kind(models.TextChoices):
        DUE_SOON = "due_soon", "Due soon"
        OVERDUE = "overdue", "Overdue"
        RESERVATION_READY = "reservation_ready", "Reserved copy ready"
        RESERVATION_EXPIRED = "reservation_expired", "Reservation expired"
        FINE_CHARGED = "fine_charged", "Fine charged"
        FINE_CLEARED = "fine_cleared", "Fine cleared"
        GENERAL = "general", "Notice"

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
    message = models.CharField(max_length=255)
    link = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional path within the site, for example /loans/.",
    )
    is_read = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["user", "is_read"],
                name="notification_by_user_state",
            )
        ]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.user.username}: {self.message}"
