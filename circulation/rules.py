"""
Circulation policy: the numbers the library runs on, and the arithmetic
that uses them.

Nothing in this module touches the database, imports a model, or knows
that a request exists. Every function answers a question using only its
own arguments, such as how much is owed on a book eleven days late.

That separation is the whole point of the file. services.py decides
whether a loan may happen and writes the rows; this file decides what a
due date is and what a fine comes to. Because the answers depend on
nothing but their arguments, the fine calculation can be tested without
creating a single row, and the day the library wants a different fine,
the change is one line in a file whose only job is policy.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

# ------------------------------------------------------------------ #
# Loans                                                              #
# ------------------------------------------------------------------ #

# How long a book may be kept before it is due back.
LOAN_PERIOD_DAYS = 7

# Business rule 3 from the assignment brief, and the only figure on this
# page the brief actually fixes. A student holding three books cannot
# borrow a fourth until one of them comes back.
MAX_ACTIVE_LOANS = 3

# How many times a single loan may be extended. One renewal of a seven
# day loan means a book can be kept for fourteen days in total.
MAX_RENEWALS = 1

# Named separately from LOAN_PERIOD_DAYS even though the two are equal
# today, because they answer different questions. A library that later
# wants renewals shorter than first loans changes this line and nothing
# else.
RENEWAL_PERIOD_DAYS = LOAN_PERIOD_DAYS

# How many days ahead of the due date a reminder is worth sending. Used
# by the notification pass, not by any rule that can refuse an action.
DUE_SOON_DAYS = 2

# ------------------------------------------------------------------ #
# Fines                                                              #
# ------------------------------------------------------------------ #

# Naira per whole day late. Decimal rather than float, for the same
# reason BorrowRecord.fine_amount is a DecimalField: 0.1 has no exact
# binary representation, so money added up in floats drifts by fractions
# of a kobo and a balance that ought to read zero eventually does not.
FINE_PER_DAY = Decimal("100.00")

# Every amount returned from this module is rounded to this many places,
# which matches the decimal_places on the field it gets stored in.
MONEY = Decimal("0.01")

# ------------------------------------------------------------------ #
# Reservations                                                       #
# ------------------------------------------------------------------ #

# Once a copy comes back and the person at the front of the queue has
# been told about it, the copy is held for them for this long. If they do
# not collect it the hold lapses and the next person is offered it.
RESERVATION_HOLD_DAYS = 3

# A cap on the waiting list, for the same reason as the loan cap. Without
# one, a single student could reserve the whole catalogue and hold up
# everybody behind them at no cost to themselves.
MAX_ACTIVE_RESERVATIONS = 3


# ------------------------------------------------------------------ #
# Dates                                                              #
# ------------------------------------------------------------------ #


def today():
    """
    The current date as the library sees it.

    localdate() and not now().date(). now() is in UTC and Lagos runs an
    hour ahead of it, so between midnight and one in the morning the UTC
    date is still yesterday. Every date in this module comes through this
    one function, so a loan taken out at half past midnight is not dated
    to the day before and a book does not go overdue an hour late.
    """
    return timezone.localdate()


def default_due_date(start=None):
    """
    The day a loan starting today is due back.

    The start argument exists for two reasons: a test can pin the date
    instead of depending on the day it happens to run, and a librarian
    recording a loan that began earlier in the week gets a due date
    measured from the loan, not from today.
    """
    # Compared against None rather than tested for truth. A date object
    # is never falsy, so `start or today()` would work, but only by
    # accident, and it would quietly break if this ever took a number.
    if start is None:
        start = today()
    return start + timedelta(days=LOAN_PERIOD_DAYS)


def renewed_due_date(current_due_date):
    """
    The new due date after a loan is renewed.

    Counted from the existing due date rather than from today, so a
    student who renews early keeps the days they had left instead of
    losing them. A loan due on the 12th, renewed on the 9th, runs to the
    19th and not to the 16th.

    services.py refuses to renew a loan that is already overdue, so this
    is never asked to extend a date that has passed.
    """
    return current_due_date + timedelta(days=RENEWAL_PERIOD_DAYS)


def is_due_soon(due_date, on=None):
    """
    True when a loan is close enough to its due date to be worth a
    reminder, and is not already overdue.

    The second half matters: an overdue book needs the overdue notice,
    not a cheerful note that it is due shortly.
    """
    if on is None:
        on = today()
    return 0 <= (due_date - on).days <= DUE_SOON_DAYS


# ------------------------------------------------------------------ #
# Money                                                              #
# ------------------------------------------------------------------ #


def days_late(due_date, returned_on=None):
    """
    How many whole days past its due date a book was, or is, or zero if
    it is not late at all.

    Whole days on purpose. due_date is a DateField rather than a
    DateTimeField precisely so that returning a book at ten in the
    morning and returning it at ten at night cost exactly the same, and
    nobody has to argue about an hour.

    Returning it on the due date itself is not late, which is what the
    less than or equal to is there for.
    """
    if returned_on is None:
        returned_on = today()
    if returned_on <= due_date:
        return 0
    return (returned_on - due_date).days


def fine_for(due_date, returned_on=None):
    """
    What is owed on a book returned on a given day.

    Returns Decimal("0.00") for anything returned on time, so a caller
    can store the result without checking it first and there is no need
    for a separate "was it late" branch anywhere else.
    """
    late = days_late(due_date, returned_on)
    # A Decimal multiplied by an int stays exact. quantize then pins the
    # result to two places, so the figure always looks like money even if
    # FINE_PER_DAY is one day set to something like 33.33.
    return (FINE_PER_DAY * late).quantize(MONEY)


# ------------------------------------------------------------------ #
# Holds                                                              #
# ------------------------------------------------------------------ #


def hold_expiry(from_moment=None):
    """
    The moment a hold placed now runs out.

    A datetime here, unlike the loan dates above. A loan is measured in
    whole days because a fine has to be predictable and arguable in
    court; a hold is a short courtesy window measured from the moment the
    copy came back, and rounding it to a whole day would either give away
    most of a day or take one away.
    """
    if from_moment is None:
        from_moment = timezone.now()
    return from_moment + timedelta(days=RESERVATION_HOLD_DAYS)


