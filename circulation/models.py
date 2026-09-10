"""
Circulation models: the loans themselves, the waitlist that forms behind
a book with no copies left, and the audit trail of who did what.

The rules that decide whether a loan may be created live in services.py,
not here. What lives here is the shape of the data and the guarantees the
database itself can enforce, so that a mistake in a view or a mistyped
shell command cannot leave the library in an impossible state.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


# The three enums below sit at module level rather than nested inside
# their models. A class body does not create a scope that a nested class
# body can see, so a Meta constraint written inside Reservation cannot
# refer to a Status class also defined inside Reservation. Keeping all of
# them out here means the constraints can name their values instead of
# repeating raw strings that nothing would catch if they drifted.


class ReservationStatus(models.TextChoices):
    """
    Where a reservation has got to.

    WAITING is in the queue, NOTIFIED means a copy came back and this
    person is being given first refusal, FULFILLED means they took it,
    EXPIRED means they were too slow, CANCELLED means they withdrew.
    """

    WAITING = "waiting", "Waiting"
    NOTIFIED = "notified", "Copy available"
    FULFILLED = "fulfilled", "Fulfilled"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


# What "in the queue" means, in one place.
#
# Those two statuses together are the definition of a live reservation: one
# person is waiting their turn, the other has a copy being held for them, and
# both are ahead of anybody joining now. The pair is asked about often enough
# that spelling it out at each site meant five copies of one rule, and a
# sixth would have arrived with the circulation views.
#
# A list rather than a tuple because every use is a __in lookup, and because
# the Meta constraint below could adopt it without the applied migration
# looking out of date.
LIVE_RESERVATION_STATUSES = [
    ReservationStatus.WAITING,
    ReservationStatus.NOTIFIED,
]


class AuditAction(models.TextChoices):
    """
    The set of events worth recording.

    Stored as short stable strings so a query for every deletion still
    works after the wording shown to a librarian has been reworded.
    """

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
    One copy of one book, out on loan to one student.

    A row is created when a book is borrowed and is never deleted. When
    the book comes back the same row gains a returned date, which is what
    turns it from an active loan into a line of borrowing history.
    """

    # PROTECT on both sides. A student who has ever borrowed a book
    # cannot be deleted out from under their own history, and neither can
    # the book. Deactivating is the way to retire either of them, which
    # is why Book carries is_active and User carries is_active.
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

    # Stamped once, at creation, and never touched again.
    borrowed_date = models.DateTimeField(auto_now_add=True)

    # A date rather than a datetime because a fine is counted in whole
    # days, so an hour either side of midnight must not change the amount
    # owed. No default is set here: the loan period is policy, it lives
    # in rules.py, and services.py fills this in when the loan is created.
    due_date = models.DateField(
        help_text="The day this book is due back. Fines start the day after.",
    )

    # Null is the marker for a loan that is still out. There is
    # deliberately no separate is_returned column, because two columns
    # saying the same thing can disagree. See the is_returned property.
    returned_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Left empty while the book is still out on loan.",
    )

    renewal_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many times this loan has been extended.",
    )

    # DecimalField, not FloatField. A float cannot hold 0.10 exactly, so
    # money added up in floats drifts by fractions of a kobo and a
    # balance that should read zero does not. Decimal is exact.
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
        # Newest loan first, which is the order both the student's history
        # page and the librarian's monitoring table want.
        ordering = ["-borrowed_date"]

        constraints = [
            # Business rule 2, made impossible rather than merely
            # checked: a student cannot hold two active loans of the same
            # book. The condition is what makes it work. A plain unique
            # constraint on student plus book would also block borrowing
            # the same book again next term, which is normal library use.
            # Restricting it to rows where returned_date is null means the
            # rule applies to current loans only.
            models.UniqueConstraint(
                fields=["student", "book"],
                condition=models.Q(returned_date__isnull=True),
                name="one_active_loan_per_student_per_book",
            ),
            # A fine can be zero but never negative, so a bug in the
            # calculation cannot turn into credit.
            models.CheckConstraint(
                condition=models.Q(fine_amount__gte=0),
                name="fine_amount_not_negative",
            ),
            # A book cannot come back before it went out. The first half
            # of the OR is what lets an active loan, with no returned date
            # at all, still satisfy the constraint.
            models.CheckConstraint(
                condition=(
                    models.Q(returned_date__isnull=True)
                    | models.Q(returned_date__gte=models.F("borrowed_date"))
                ),
                name="returned_after_borrowed",
            ),
        ]

        indexes = [
            # Every dashboard page asks the same question: which books
            # does this student currently have out. That filters on
            # student and on returned_date being null, so one index
            # covering both columns serves it.
            models.Index(
                fields=["student", "returned_date"],
                name="loan_by_student_and_state",
            ),
        ]

    def __str__(self):
        """Shown in the admin list and in the audit log."""
        state = "returned" if self.is_returned else f"due {self.due_date}"
        return f"{self.book.title} to {self.student} ({state})"

    @property
    def is_returned(self):
        """
        True once the book is back on the shelf.

        Derived from returned_date rather than stored, so there is exactly
        one fact in the database and nothing to keep in step.
        """
        return self.returned_date is not None

    @property
    def is_overdue(self):
        """
        True if this book is still out and the due date has passed.

        localdate() is used rather than now().date(). now() is in UTC, and
        Lagos is an hour ahead, so between midnight and 1am local time the
        UTC date is still yesterday. Comparing against that would let an
        overdue book look fine for an hour every night.
        """
        return not self.is_returned and timezone.localdate() > self.due_date

    @property
    def days_overdue(self):
        """
        How many whole days late this loan currently is, or zero.

        Only meaningful while the book is still out. Once it is back, the
        amount that was owed is recorded in fine_amount instead.
        """
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days


class Reservation(models.Model):
    """
    A student's place in the queue for a book that has no copies left.

    When a copy comes back, the oldest waiting reservation is moved to
    NOTIFIED and held for that student for a fixed number of days. If they
    do not collect it in time the hold expires and the next person in line
    gets their turn.
    """

    # CASCADE on both, unlike BorrowRecord. A reservation is a pending
    # intention, not a record of something that happened, so there is
    # nothing worth keeping once either the student or the book is gone.
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

    # Set when a copy is offered to this student.
    notified_date = models.DateTimeField(null=True, blank=True)

    # The moment the hold lapses. A datetime rather than a date because a
    # hold is a short window measured from when the copy came back, not a
    # whole day like a loan.
    expires_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the offer of a copy runs out.",
    )

    class Meta:
        # Oldest first. This single line is the whole first in first out
        # waitlist: any query for a book's reservations already comes back
        # in the order the queue formed, so no view has to sort it.
        ordering = ["reserved_date"]

        constraints = [
            # One live reservation per student per book. Restricted to the
            # two active states so that a student whose earlier hold
            # expired, or who cancelled, can join the queue again.
            #
            # Spelled out rather than using LIVE_RESERVATION_STATUSES, which
            # is the same pair. Anything inside Meta is a migration question,
            # and this one is not worth asking: swapping in the constant
            # changes nothing the database can see and nothing that
            # makemigrations would record.
            models.UniqueConstraint(
                fields=["student", "book"],
                condition=models.Q(
                    status__in=[
                        ReservationStatus.WAITING,
                        ReservationStatus.NOTIFIED,
                    ]
                ),
                name="one_active_reservation_per_student_per_book",
            ),
        ]

        indexes = [
            # Returning a book asks: who is next in line for this title.
            # That filters on book and status, so both belong in one index.
            models.Index(
                fields=["book", "status"],
                name="reservation_by_book_state",
            ),
        ]

    def __str__(self):
        """Shown in the admin list and in the audit log."""
        return f"{self.student} waiting for {self.book.title}"

    @property
    def is_active(self):
        """True while this reservation still entitles the student to a copy."""
        # The shared list, so this cannot disagree with the queue queries in
        # services.py about what being in the queue means. A set would read
        # marginally faster on two items and would be a second spelling of
        # the same rule, which costs more than it saves.
        return self.status in LIVE_RESERVATION_STATUSES

    @property
    def has_expired(self):
        """
        True when a copy was offered but the hold window has run out.

        The status is still NOTIFIED at this point. Actually moving it to
        EXPIRED is a write, so it belongs in services.py, not in a
        property that a template might touch during a GET request.
        """
        return (
            self.status == ReservationStatus.NOTIFIED
            and self.expires_date is not None
            and timezone.now() > self.expires_date
        )

    def queue_position(self):
        """
        This reservation's place in the queue, counting from one.

        Deliberately a method and not a property, because it runs a COUNT
        query every time it is called. Written as a method, a template
        that calls it inside a loop makes that cost visible in the code
        rather than hiding one query per row behind an attribute.
        """
        ahead = Reservation.objects.filter(
            book=self.book,
            status=ReservationStatus.WAITING,
            reserved_date__lt=self.reserved_date,
        ).count()
        return ahead + 1


class AuditLog(models.Model):
    """
    An append only record of every action that changed something.

    The point of a log like this is that it survives the thing it
    describes. If a librarian deletes a book, the interesting record is
    precisely that the book is gone, so the entry cannot depend on the
    book's row still existing.
    """

    # SET_NULL, not PROTECT and not CASCADE. CASCADE would erase a
    # departing librarian's entire trail, which defeats the purpose.
    # PROTECT would make the account undeletable. SET_NULL keeps the
    # entries and lets the account go, which is why the actor's name is
    # also written into detail below.
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

    # A text snapshot such as "Book #12 Things Fall Apart", not a foreign
    # key. A foreign key would either block the deletion it is meant to
    # record or be nulled by it, and a generic relation would do the same
    # while adding a join to every read. Text is the only form that still
    # means something after the row it names has gone.
    target = models.CharField(
        max_length=255,
        help_text="What was acted on, written out as text at the time.",
    )

    detail = models.TextField(
        blank=True,
        help_text="Anything else worth keeping, such as what changed.",
    )

    # Recorded because an audit trail that cannot distinguish two people
    # sharing an account name is not much of an audit trail. Nullable
    # because actions taken from a management command have no request.
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        # Most recent first, which is how a log is read.
        ordering = ["-timestamp"]

    def __str__(self):
        """Shown in the admin list."""
        actor = self.user or "deleted account"
        return f"{self.timestamp:%Y-%m-%d %H:%M} {actor} {self.get_action_display()}"

    def save(self, *args, **kwargs):
        """
        Allow this row to be created, then refuse to change it.

        An audit trail that can be quietly edited proves nothing, so
        editing is blocked in code rather than left to good intentions.

        The test is _state.adding rather than a check on pk, because a
        fixture loaded by loaddata arrives with its primary key already
        filled in and would look like an edit. _state.adding stays True
        until the row has actually been written or read back from the
        database, so a fixture still loads and a genuine second save on an
        existing row still raises.
        """
        if not self._state.adding:
            raise ValueError(
                "Audit log entries are a permanent record and cannot be "
                "edited once written."
            )
        super().save(*args, **kwargs)
