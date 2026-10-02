"""
Circulation business logic: the only place in the project where a book
changes hands.

Every rule the assignment lists is enforced here rather than in a view,
so there is one answer to "may this happen" no matter whether the request
came from a page, the admin, a management command or a test. A view's job
is reduced to asking, catching the refusal and choosing what to say.

Three habits run through the whole file.

Each operation opens a transaction and re-reads the book with
select_for_update(), so the checks and the write that follows them cannot
be split apart by another request. On SQLite that lock is a silent no
operation, because the backend does not support row locking and Django
simply omits the clause, but SQLite serialises writers at the database
level anyway; the line is written for the day this runs on PostgreSQL,
where it becomes real.

Counts on the shelf move with an F() expression, so the subtraction
happens inside the SQL statement instead of being read into Python and
written back. That is what makes it impossible for two students to read
"one copy left" at the same moment and both take it.

Where a role decides something, the split is deliberate. Whether somebody
may reach an operation at all is a property of the user, so it is checked
by the decorators in accounts/decorators.py before a view runs. Whether a
particular loan or reservation is theirs is a property of the row, which
no decorator can see, so it is checked here.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from catalog.models import Book
from dashboard.models import Notification

from . import exceptions, rules
from .models import (
    LIVE_RESERVATION_STATUSES,
    AuditAction,
    AuditLog,
    BorrowRecord,
    Reservation,
    ReservationStatus,
)

# ------------------------------------------------------------------ #
# Small helpers                                                      #
# ------------------------------------------------------------------ #


def client_ip(request):
    """
    The address a request came from, or None when there is no request.

    REMOTE_ADDR only, deliberately. The X-Forwarded-For header is the
    usual way to see through a proxy, but it is sent by the client, so
    anything read from it can be invented freely and an audit trail built
    on it records whatever the attacker typed. It is only trustworthy when
    a proxy you control overwrites it, so it stays unread until this is
    actually deployed behind one, at which point this function is the one
    place to change.
    """
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def _path_or_blank(name, **kwargs):
    """
    Reverse a URL name, or give back an empty string if it does not exist
    yet.

    Notification.link is optional by design, which is what makes this
    safe: a notification with no link still says what it needs to say.
    Circulation's own URL patterns arrive in a later task, so without this
    the first borrowed book would raise NoReverseMatch and take down the
    borrow itself, failing something essential for the sake of something
    decorative.
    """
    try:
        return reverse(name, kwargs=kwargs) if kwargs else reverse(name)
    except NoReverseMatch:
        return ""


def book_target(book):
    """
    Describe a book for the audit log, as text.

    AuditLog.target is a snapshot rather than a foreign key so that an
    entry recording a deletion still says what was deleted. The primary
    key is kept in the text because two books can share a title.

    Public, along with the two below and record_action, because signals.py
    writes audit entries too and both modules must describe the same thing
    the same way. One shared spelling here is why a query for a book by
    name finds every entry about it, whichever module wrote them.
    """
    return f"Book #{book.pk} {book.title}"


def loan_target(record):
    """Describe a loan for the audit log, as text."""
    return f"Loan #{record.pk} {record.book.title} to {record.student}"


def reservation_target(reservation):
    """Describe a reservation for the audit log, as text."""
    return (
        f"Reservation #{reservation.pk} {reservation.book.title} "
        f"for {reservation.student}"
    )


def record_action(action, target, *, user=None, detail="", request=None):
    """
    Write one audit entry.

    The user is nulled unless it is a real signed in account, because
    AnonymousUser cannot be stored in a foreign key and a management
    command has no user at all. Either way the entry is still written,
    which is the point: an audit trail that skips the awkward cases is
    not one.
    """
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        target=target,
        detail=detail,
        ip_address=client_ip(request),
    )


def _notify(user, kind, message, link=""):
    """
    Leave a message for a member inside the site.

    Separate from Django's messages framework on purpose. A framework
    message lives in the session and vanishes the moment it is shown, so
    it suits "book borrowed" and not "the copy you reserved is ready",
    which has to survive signing out and still be waiting tomorrow.
    """
    Notification.objects.create(
        user=user,
        kind=kind,
        message=message,
        link=link,
    )


# ------------------------------------------------------------------ #
# Questions about the current state                                  #
# ------------------------------------------------------------------ #

# These are ordinary functions returning querysets rather than model
# managers, because they are asked by the dashboard and by the rules
# below, and having one definition of "an active loan" shared by both
# means a page can never disagree with the rule that governs it.


def active_loans(student):
    """
    Every book this student currently has out.

    A null returned_date is the one fact that marks a loan as live, which
    is why BorrowRecord has no separate is_returned column to fall out of
    step with it. This filter matches the loan_by_student_and_state index
    exactly, so it stays cheap as the table fills up.
    """
    return BorrowRecord.objects.filter(student=student, returned_date__isnull=True)


def active_reservations(student):
    """Every queue this student is currently waiting in."""
    return Reservation.objects.filter(
        student=student,
        status__in=LIVE_RESERVATION_STATUSES,
    )


def _live_holds(book):
    """
    Reservations for this book that are currently holding a copy back.

    Notified and not yet lapsed. Each one of these has a copy on the shelf
    with its name on it, which is what the borrowing rule below has to
    account for.
    """
    return Reservation.objects.filter(
        book=book,
        status=ReservationStatus.NOTIFIED,
        expires_date__gt=timezone.now(),
    )


def _copies_free_for(book, student):
    """
    How many copies this particular student could take right now.

    The shelf count minus the copies promised to other people. A hold
    belonging to this student is excluded from the subtraction, because
    that copy is being kept for them and taking it is exactly what it is
    there for.

    Can return a negative number if the data is odd, which is harmless:
    every caller only asks whether the result is greater than zero.
    """
    held_for_others = _live_holds(book).exclude(student=student).count()
    return book.available_quantity - held_for_others


def _anyone_waiting(book, *, other_than=None):
    """
    True if a queue has formed for this book.

    Used by the renewal rule. The borrower themselves is excluded, since a
    student who is holding the book and also sitting in its queue should
    not be blocked from renewing by their own place in line.
    """
    queryset = Reservation.objects.filter(
        book=book,
        status__in=LIVE_RESERVATION_STATUSES,
    )
    if other_than is not None:
        queryset = queryset.exclude(student=other_than)
    return queryset.exists()


# ------------------------------------------------------------------ #
# The waiting list                                                   #
# ------------------------------------------------------------------ #


def _lock_book(book):
    """
    Re-read a book inside the current transaction and hold its row.

    Two things are happening. The row is locked, so no other request can
    change the shelf count between the checks below and the write that
    follows them. And the instance is re-read, so the counts being checked
    are the ones in the database now, not the ones that happened to be
    loaded when the view rendered its page a minute ago.

    select_for_update() raises if it is called outside a transaction,
    which is a feature: it makes it impossible to use this helper in a way
    that would not actually protect anything.
    """
    return Book.objects.select_for_update().get(pk=book.pk)


def expire_lapsed_holds(book=None, *, request=None):
    """
    Retire every hold whose collection window has run out, and tell the
    students who lost their turn. Returns how many lapsed.

    Called at the start of borrowing and reserving rather than from a
    scheduled job, so a hold nobody collected is cleared at the exact
    moment it would otherwise be standing in somebody's way. That is what
    lets the whole reservation system be correct on a machine with no cron
    running, which is the machine this project will be marked on.

    Nothing is written to the audit log here. That log records what people
    did, and this is the passage of time; the reservation's own status and
    expires_date already say precisely what happened and when.
    """
    lapsed = Reservation.objects.filter(
        status=ReservationStatus.NOTIFIED,
        expires_date__lte=timezone.now(),
    ).select_related("book", "student")

    # Narrowed to one title when a caller is dealing with one title, and
    # left wide for a sweep over the whole library.
    if book is not None:
        lapsed = lapsed.filter(book=book)

    count = 0
    for reservation in lapsed:
        reservation.status = ReservationStatus.EXPIRED
        # update_fields keeps the UPDATE to the column that changed, so
        # this cannot quietly write back a stale value in another column.
        reservation.save(update_fields=["status"])
        _notify(
            reservation.student,
            Notification.Kind.RESERVATION_EXPIRED,
            f"The copy of {reservation.book.title} held for you was not "
            f"collected in time, so it has gone to the next member waiting.",
            link=_path_or_blank("catalog:book_detail", pk=reservation.book_id),
        )
        count += 1
    return count


def offer_available_copies(book, *, request=None):
    """
    Hand any unclaimed copy on the shelf to the front of the queue, and
    tell whoever it now belongs to. Returns how many copies were offered.

    Called after a book comes back and after a hold is cancelled, which
    are the two moments a copy can become free while somebody is waiting.

    A withdrawn book offers nothing, whatever its shelf count says.
    """
    # The shelf count is re-read rather than taken from the instance
    # passed in. Callers reach this after an F() expression has changed
    # the column in the database, and an F() update leaves the Python
    # attribute holding the old number. is_active is re-read for a related
    # reason: withdrawing a book cancels the holds on it, and cancelling a
    # hold is one of the two things that calls this function, so the flag
    # on the instance in hand can already be a step behind the row.
    book.refresh_from_db(fields=["available_quantity", "is_active"])

    # A book taken out of the lending collection is offered to nobody.
    # Nothing else in this function would notice. Its copies are still on
    # the shelf as far as the column is concerned, so the arithmetic below
    # would find a spare one and send somebody a notification promising a
    # loan that borrow_book then refuses with BookWithdrawn. A queue that
    # goes quiet is a smaller unkindness than a promise the library cannot
    # keep.
    if not book.is_active:
        return 0

    # Every live hold already has a copy with its name on it, so only what
    # is left over can be offered to anybody new.
    spare = book.available_quantity - _live_holds(book).count()
    if spare <= 0:
        return 0

    # order_by is stated rather than left to Reservation.Meta.ordering,
    # which happens to say the same thing. First in, first out is the
    # entire fairness guarantee of a waiting list, so it is spelled out
    # here where it is being relied on. The slice asks the database for
    # only as many rows as there are copies to give away.
    waiting = (
        Reservation.objects.filter(book=book, status=ReservationStatus.WAITING)
        .select_related("student")
        .order_by("reserved_date")[:spare]
    )

    now = timezone.now()
    offered = 0
    for reservation in waiting:
        reservation.status = ReservationStatus.NOTIFIED
        reservation.notified_date = now
        reservation.expires_date = rules.hold_expiry(now)
        reservation.save(
            update_fields=["status", "notified_date", "expires_date"]
        )

        # localtime() converts out of UTC before the date is read, so a
        # hold expiring just after midnight Lagos time is not described as
        # expiring the day before. The day is interpolated separately
        # because the strftime code for an unpadded day is a GNU extension
        # and this project is developed on Windows.
        until = timezone.localtime(reservation.expires_date)
        _notify(
            reservation.student,
            Notification.Kind.RESERVATION_READY,
            f"A copy of {book.title} is ready for you. It is held until "
            f"{until.day} {until:%B}.",
            link=_path_or_blank("catalog:book_detail", pk=book.pk),
        )
        offered += 1
    return offered


def refresh_queue(book, *, request=None):
    """
    Bring one book's waiting list up to date.

    Clear out holds that have run their course, then offer whatever is now
    unclaimed to the people still waiting. Every operation below that
    could change either side of that picture calls this, so no rule has to
    reason about a queue that has gone stale.
    """
    expire_lapsed_holds(book, request=request)
    offer_available_copies(book, request=request)


# ------------------------------------------------------------------ #
# Borrowing                                                          #
# ------------------------------------------------------------------ #


@transaction.atomic
def borrow_book(*, student, book, request=None):
    """
    Lend one copy of a book to a student, or refuse and say why.

    This one function carries four of the six business rules in the
    assignment brief. Rule 5, that only a signed in member may borrow, is
    handled a layer up by LoginRequiredMiddleware, and rule 6, that
    librarian work is closed to students, does not apply to borrowing.

    Raises a subclass of exceptions.CirculationError on any refusal and
    returns the new BorrowRecord otherwise. Because the whole function is
    one transaction, a refusal raised part way through unwinds anything
    already written, so a failed borrow leaves nothing behind.

    Keyword only arguments on purpose. borrow_book(a, b) reads the same
    whichever way round the two are, and getting them the wrong way round
    would be a confusing failure deep inside a query.
    """
    # Take the row and read the counts as they stand now, not as they
    # stood when the page the student clicked was rendered.
    book = _lock_book(book)

    # Clear expired holds and pass unclaimed copies down the queue before
    # anything is decided, so this student is neither blocked by a hold
    # that has already lapsed nor allowed past one that is still good.
    refresh_queue(book, request=request)

    # Rule 1, first half. A withdrawn book is unavailable whatever the
    # shelf count says.
    if not book.is_active:
        raise exceptions.BookWithdrawn()

    # Rule 2, checked before the shelf count is looked at. A student
    # holding the library's only copy would otherwise be told there were
    # none left, which is true but unhelpful, when what they need to hear
    # is that they already have it.
    if active_loans(student).filter(book=book).exists():
        raise exceptions.AlreadyBorrowed()

    # Rule 3. This is the one rule that cannot be a database constraint,
    # because deciding it needs a count of the student's other loans and a
    # constraint can only see the row being written. Counted inside the
    # lock, so two quick clicks cannot both see two loans and both pass.
    if active_loans(student).count() >= rules.MAX_ACTIVE_LOANS:
        raise exceptions.LoanLimitReached()

    # Rule 1, second half.
    if book.available_quantity < 1:
        raise exceptions.BookNotAvailable()

    # Not in the brief, but the reservation queue is meaningless without
    # it: every copy on the shelf is spoken for by somebody who waited.
    if _copies_free_for(book, student) < 1:
        raise exceptions.CopiesHeldForOthers()

    # Rule 4, borrowing side. Two things make this safe. The subtraction
    # is an F() expression, so it happens inside the SQL statement and
    # never as a read in Python followed by a write. And the filter
    # repeats the availability test, so the database only touches the row
    # if a copy is still there; if it is not, zero rows come back and the
    # borrow is refused rather than driving the count negative. That makes
    # this correct even on a backend where the row lock above does
    # nothing. Underneath both, the table itself carries CHECK constraints
    # keeping the count at or above zero and at or below the number of
    # copies owned.
    changed = Book.objects.filter(pk=book.pk, available_quantity__gte=1).update(
        available_quantity=F("available_quantity") - 1
    )
    if not changed:
        raise exceptions.BookNotAvailable()

    # An F() update changes the column in the database and leaves the
    # Python attribute holding the old number, so it is re-read before the
    # instance is handed back to the caller.
    book.refresh_from_db(fields=["available_quantity"])

    record = BorrowRecord.objects.create(
        student=student,
        book=book,
        # The only place a due date is ever set from scratch. The period
        # itself is policy and lives in rules.py.
        due_date=rules.default_due_date(),
    )

    # If this student was in the queue for this book, that is now settled.
    # Doing it here rather than in the view means it is impossible to
    # collect a reserved copy and still be left sitting in its queue.
    own_hold = active_reservations(student).filter(book=book).first()
    if own_hold is not None:
        own_hold.status = ReservationStatus.FULFILLED
        own_hold.save(update_fields=["status"])

    record_action(
        AuditAction.BORROW,
        loan_target(record),
        user=student,
        detail=f"Due {record.due_date.isoformat()}.",
        request=request,
    )
    return record


# ------------------------------------------------------------------ #
# Returning                                                          #
# ------------------------------------------------------------------ #


@transaction.atomic
def return_book(*, record, actor=None, request=None):
    """
    Take a book back, work out what is owed on it, and move the queue on.

    The actor is whoever pressed the button, which is not always the
    borrower: a librarian processing returns at the desk is the other
    normal case, and a management command has no actor at all. It decides
    both what the audit entry says and whether the ownership check below
    applies.

    Returns the updated BorrowRecord. Its fine_amount is the figure owed,
    which is Decimal("0.00") for anything brought back on time.
    """
    # The book row is always taken before the loan row, in this function
    # and in every other one here. Two operations that lock the same pair
    # of rows in opposite orders can each hold what the other is waiting
    # for, and a fixed order is what makes that impossible.
    book = _lock_book(record.book)
    record = (
        BorrowRecord.objects.select_for_update()
        .select_related("book", "student")
        .get(pk=record.pk)
    )

    # Most often a double submission: somebody presses Return, the page is
    # slow to come back, and they press it again. Refusing the second
    # attempt is what stops one book putting two copies on the shelf.
    if record.returned_date is not None:
        raise exceptions.AlreadyReturned()

    # Ownership, which no decorator could check because it depends on this
    # particular row. A librarian is exempt, since handling other people's
    # returns is the job.
    if (
        actor is not None
        and actor != record.student
        and not getattr(actor, "is_librarian", False)
    ):
        raise exceptions.NotYourLoan()

    returned_on = rules.today()
    record.returned_date = timezone.now()

    # The fine is worked out once, here, from the two dates, and then
    # frozen. Nothing accrues in the background: while a book is out the
    # running figure is derived on the fly by BorrowRecord.days_overdue,
    # and the moment it comes back that figure becomes a stored fact that
    # cannot drift afterwards.
    record.fine_amount = rules.fine_for(record.due_date, returned_on)
    record.save(update_fields=["returned_date", "fine_amount"])

    # Rule 4, returning side. An F() expression again, so the addition
    # happens in SQL. No conditional filter is needed here because the
    # AlreadyReturned check above guarantees this increment is matched by
    # exactly one earlier decrement; the table's own
    # available_not_greater_than_quantity constraint is the backstop if
    # that assumption is ever broken.
    Book.objects.filter(pk=book.pk).update(
        available_quantity=F("available_quantity") + 1
    )
    book.refresh_from_db(fields=["available_quantity"])

    late = rules.days_late(record.due_date, returned_on)
    detail = f"Returned {returned_on.isoformat()}."
    if late:
        detail += f" {late} day(s) late, fine {record.fine_amount:.2f}."

    record_action(
        AuditAction.RETURN,
        loan_target(record),
        # Whoever actually did it. Falls back to the borrower so a return
        # processed by a command still names somebody sensible.
        user=actor or record.student,
        detail=detail,
        request=request,
    )

    # A fine needs to survive being read once, so it is a notification
    # rather than a flash message. The borrower is told even when a
    # librarian was the one who processed the return.
    if record.fine_amount > Decimal("0.00"):
        _notify(
            record.student,
            Notification.Kind.FINE_CHARGED,
            f"{record.book.title} came back {late} day(s) late, so a fine "
            f"of {record.fine_amount:.2f} naira is owed.",
            link=_path_or_blank("catalog:book_detail", pk=record.book_id),
        )

    # A copy has just become free, which is the main moment somebody in
    # the queue gets their turn.
    refresh_queue(book, request=request)
    return record


# ------------------------------------------------------------------ #
# Renewing                                                           #
# ------------------------------------------------------------------ #


@transaction.atomic
def renew_loan(*, record, actor=None, request=None):
    """
    Push a loan's due date back, or refuse and say why.

    Not in the assignment brief, and the three refusals below are the
    reason it is worth having rather than being a single button that
    always works. A renewal that could be granted on an overdue book would
    be a way to make a fine vanish. A renewal with no limit would be a
    lease. A renewal granted while somebody is waiting would mean the
    queue never moves at all.
    """
    book = _lock_book(record.book)
    record = (
        BorrowRecord.objects.select_for_update()
        .select_related("book", "student")
        .get(pk=record.pk)
    )

    if record.returned_date is not None:
        raise exceptions.AlreadyReturned()

    if (
        actor is not None
        and actor != record.student
        and not getattr(actor, "is_librarian", False)
    ):
        raise exceptions.NotYourLoan()

    if record.renewal_count >= rules.MAX_RENEWALS:
        raise exceptions.RenewalLimitReached()

    if record.is_overdue:
        raise exceptions.CannotRenewOverdue()

    # The borrower's own place in the queue, if they have one, is ignored.
    # Being both the holder and a waiter is odd but harmless, and it should
    # not block them from renewing against themselves.
    if _anyone_waiting(book, other_than=record.student):
        raise exceptions.CannotRenewWithQueue()

    was_due = record.due_date
    record.due_date = rules.renewed_due_date(was_due)
    # An F() expression rather than reading the count and adding one, for
    # the same reason as the shelf count: the addition happens in SQL.
    record.renewal_count = F("renewal_count") + 1
    record.save(update_fields=["due_date", "renewal_count"])

    # Until this line renewal_count holds the expression itself rather than
    # a number, so anything that read it would get a query object.
    record.refresh_from_db(fields=["renewal_count"])

    record_action(
        AuditAction.RENEW,
        loan_target(record),
        user=actor or record.student,
        detail=(
            f"Due date moved from {was_due.isoformat()} to "
            f"{record.due_date.isoformat()}. Renewal "
            f"{record.renewal_count} of {rules.MAX_RENEWALS}."
        ),
        request=request,
    )
    return record


# ------------------------------------------------------------------ #
# Reserving                                                          #
# ------------------------------------------------------------------ #


@transaction.atomic
def reserve_book(*, student, book, request=None):
    """
    Put a student in the queue for a book that has no copy free for them.

    The queue exists so that wanting a popular book is not a matter of
    refreshing the catalogue page until you get lucky. Everything that
    makes it fair is elsewhere: Reservation.Meta.ordering keeps it first in
    first out, offer_available_copies works down it in that order, and
    borrow_book refuses to let a passer by take a copy being held.
    """
    book = _lock_book(book)

    # Bring the queue up to date first. Without this, a book whose only
    # hold lapsed an hour ago would look unavailable and this student would
    # join a queue when they could simply have borrowed it.
    refresh_queue(book, request=request)

    if not book.is_active:
        raise exceptions.BookWithdrawn()

    # Reserving a book that is already in your bag is a mistake worth
    # naming rather than quietly allowing.
    if active_loans(student).filter(book=book).exists():
        raise exceptions.AlreadyBorrowed()

    # Checked before the availability test below, because the database
    # would refuse this row anyway through the partial unique constraint
    # one_active_reservation_per_student_per_book, and a named rule reads
    # better than an IntegrityError.
    if active_reservations(student).filter(book=book).exists():
        raise exceptions.AlreadyReserved()

    # There is nothing to wait for if a copy is free for this student. Note
    # that this asks what is free for them specifically, so a book whose
    # every copy is held for other people can still be reserved.
    if _copies_free_for(book, student) >= 1:
        raise exceptions.CopiesAvailable()

    if active_reservations(student).count() >= rules.MAX_ACTIVE_RESERVATIONS:
        raise exceptions.ReservationLimitReached()

    # Status defaults to WAITING and reserved_date is stamped by
    # auto_now_add, and that timestamp is the student's place in the queue.
    reservation = Reservation.objects.create(student=student, book=book)

    record_action(
        AuditAction.RESERVE,
        reservation_target(reservation),
        user=student,
        detail=f"Position {reservation.queue_position()} in the queue.",
        request=request,
    )
    return reservation


@transaction.atomic
def cancel_reservation(*, reservation, actor=None, request=None):
    """
    Give up a place in a queue.

    The row is kept and marked cancelled rather than deleted, which is what
    lets the same student join the queue again later: the unique constraint
    on the pair only covers the waiting and notified states.
    """
    # The book is locked even though no shelf count changes here, because
    # cancelling a hold hands a copy to the next person and that has to
    # happen under the same lock as any other change to the queue.
    book = _lock_book(reservation.book)
    reservation = (
        Reservation.objects.select_for_update()
        .select_related("book", "student")
        .get(pk=reservation.pk)
    )

    if (
        actor is not None
        and actor != reservation.student
        and not getattr(actor, "is_librarian", False)
    ):
        raise exceptions.NotYourReservation()

    if not reservation.is_active:
        raise exceptions.ReservationNotActive()

    # Noted before the status is overwritten. If this student was holding a
    # copy, cancelling releases it and somebody else's turn comes early.
    was_holding_a_copy = reservation.status == ReservationStatus.NOTIFIED

    reservation.status = ReservationStatus.CANCELLED
    reservation.save(update_fields=["status"])

    record_action(
        AuditAction.RESERVATION_CANCEL,
        reservation_target(reservation),
        user=actor or reservation.student,
        request=request,
    )

    if was_holding_a_copy:
        refresh_queue(book, request=request)
    return reservation


# ------------------------------------------------------------------ #
# Fines                                                              #
# ------------------------------------------------------------------ #


@transaction.atomic
def mark_fine_paid(*, record, actor=None, request=None):
    """
    Record that a fine has been settled at the desk.

    Money is not taken here. This only writes down that it was handed over,
    which is why the audit entry naming the librarian who wrote it down
    matters more than usual.

    That this is librarian work is enforced by librarian_required on the
    view, following the split described at the top of this file: a role is a
    property of the user and belongs in a decorator, while whether a
    particular loan is yours is a property of the row and belongs here.
    """
    # No book is locked, because nothing about the shelf changes. Only the
    # loan row is taken, so two librarians working through the same list
    # cannot both record the same payment.
    record = (
        BorrowRecord.objects.select_for_update()
        .select_related("book", "student")
        .get(pk=record.pk)
    )

    # Refused rather than ignored. A fine marked paid when none was charged
    # would leave an audit entry describing a payment that never happened.
    if record.fine_amount <= Decimal("0.00"):
        raise exceptions.NoFineOwed()

    if record.fine_paid:
        raise exceptions.FineAlreadyPaid()

    record.fine_paid = True
    record.save(update_fields=["fine_paid"])

    record_action(
        AuditAction.FINE_PAID,
        loan_target(record),
        user=actor,
        detail=f"{record.fine_amount:.2f} naira settled.",
        request=request,
    )
    _notify(
        record.student,
        Notification.Kind.FINE_CLEARED,
        f"The fine of {record.fine_amount:.2f} naira on "
        f"{record.book.title} has been marked as settled. Thank you.",
    )
    return record








