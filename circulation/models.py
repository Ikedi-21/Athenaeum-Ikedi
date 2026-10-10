"""
Models for circulation: loans, reservations, and institutional audit logging.
"""

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint
from django.utils import timezone

from . import rules


class ReservationStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    NOTIFIED = "notified", "Copy available"
    FULFILLED = "fulfilled", "Fulfilled"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


LIVE_RESERVATION_STATUSES = [
    ReservationStatus.WAITING,
    ReservationStatus.NOTIFIED,
]


class AuditAction(models.TextChoices):
    BORROW = "borrow", "Book borrowed"
    RETURN = "return", "Book returned"
    RENEW = "renew", "Loan renewed"
    RESERVE = "reserve", "Book reserved"
    RESERVATION_CANCEL = "reservation_cancel", "Reservation cancelled"
    FINE_PAID = "fine_paid", "Fine marked paid"
    BOOK_CREATE = "book_create", "Book added"
    BOOK_UPDATE = "book_update", "Book edited"
    BOOK_WITHDRAW = "book_withdraw", "Book withdrawn from catalogue"
    BOOK_DELETE = "book_delete", "Book deleted"
    ROLE_CHANGE = "role_change", "Role changed"


class BorrowRecord(models.Model):
    """
    A single borrowing event for a member and book copy.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="borrow_records",
    )
    book = models.ForeignKey(
        "catalog.Book",
        on_delete=models.PROTECT,
        related_name="borrow_records",
    )
    borrowed_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(
        help_text="The day this book is due back. Fines start the day after."
    )
    returned_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Left empty while the book is still out on loan.",
    )
    renewal_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many times this loan has been extended.",
    )
    fine_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Charged on return if the book was late.",
    )
    fine_paid = models.BooleanField(
        default=False,
        help_text="Ticked by a librarian once the fine has been settled.",
    )

    class Meta:
        ordering = ["-borrowed_date"]
        indexes = [
            models.Index(
                fields=["student", "returned_date"],
                name="loan_by_student_and_state",
            )
        ]
        constraints = [
            UniqueConstraint(
                condition=Q(returned_date__isnull=True),
                fields=("student", "book"),
                name="one_active_loan_per_student_per_book",
            ),
            CheckConstraint(
                condition=Q(fine_amount__gte=0),
                name="fine_amount_not_negative",
            ),
            CheckConstraint(
                condition=Q(returned_date__isnull=True)
                | Q(returned_date__gte=F("borrowed_date")),
                name="returned_after_borrowed",
            ),
        ]

    def __str__(self):
        return f"{self.book.title} borrowed by {self.student.username}"

    @property
    def is_active(self):
        return self.returned_date is None

    @property
    def is_overdue(self):
        today = timezone.localdate()
        return self.is_active and self.due_date < today

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return rules.days_late(self.due_date, timezone.localdate())

    @property
    def estimated_fine(self):
        if not self.is_overdue:
            return Decimal("0.00")
        return rules.fine_for(self.due_date, timezone.localdate())


class Reservation(models.Model):
    """
    Queue position hold placed on a checked-out book.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    book = models.ForeignKey(
        "catalog.Book",
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    reserved_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.WAITING,
    )
    notified_date = models.DateTimeField(null=True, blank=True)
    expires_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the offer of a copy runs out.",
    )

    class Meta:
        ordering = ["reserved_date"]
        indexes = [
            models.Index(
                fields=["book", "status"],
                name="reservation_by_book_state",
            )
        ]
        constraints = [
            UniqueConstraint(
                condition=Q(status__in=["waiting", "notified"]),
                fields=("student", "book"),
                name="one_active_reservation_per_student_per_book",
            )
        ]

    def __str__(self):
        return f"Hold on {self.book.title} for {self.student.username} ({self.get_status_display()})"

    @property
    def has_expired(self):
        if self.status == ReservationStatus.NOTIFIED and self.expires_date:
            return timezone.now() > self.expires_date
        return False

    def queue_position(self):
        """Current zero-based or 1-based index in waiting queue."""
        if self.status == ReservationStatus.NOTIFIED:
            return 1
        waiting = list(
            Reservation.objects.filter(
                book=self.book,
                status=ReservationStatus.WAITING,
            ).order_by("reserved_date").values_list("pk", flat=True)
        )
        try:
            return waiting.index(self.pk) + 1
        except ValueError:
            return 1


class AuditLog(models.Model):
    """
    Immutable forensic ledger tracking every library transaction and administrative change.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    action = models.CharField(
        max_length=32,
        choices=AuditAction.choices,
        db_index=True,
    )
    target = models.CharField(
        max_length=255,
        help_text="What was acted on, written out as text at the time.",
    )
    detail = models.TextField(
        blank=True,
        help_text="Anything else worth keeping, such as what changed.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        user_str = self.user.username if self.user else "System"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.get_action_display()} by {user_str}: {self.target}"
