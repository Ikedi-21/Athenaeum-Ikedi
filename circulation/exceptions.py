"""
The refusals circulation can issue.

Every rule in this app reports a failure by raising one of these classes,
which buys two things worth the file.

A view catches the single base class and turns any refusal into a message
on the page, so no view ever repeats a rule or needs to know which rules
exist. And a test catches the exact subclass, so "a student cannot borrow
a fourth book" is proved by name rather than by matching words in a
sentence that a later rewording would silently break.

Each class carries its own wording, so the sentence a borrower reads sits
here beside the rule it belongs to instead of being scattered through the
views. Where a message quotes a number, it reads it from rules.py, so
changing the loan cap changes the message too.
"""

from . import rules


class CirculationError(Exception):
    """
    Base class for every refusal in this app.

    A caller that only wants to show the reason on the page catches this
    and prints str(exc). A caller that needs to tell one refusal from
    another catches the specific subclass instead.
    """

    # Used when the class is raised with no argument, which is the normal
    # case. A caller with something more specific to say passes its own
    # message and that wins.
    message = "That action is not allowed right now."

    def __init__(self, message=None):
        """Fall back to the class's own wording when none is given."""
        # The final text is handed to Exception itself rather than only
        # stored on self, so str(exc), repr(exc) and pickling all behave
        # the way they do for any other exception.
        super().__init__(message or self.message)


# ------------------------------------------------------------------ #
# Borrowing                                                          #
# ------------------------------------------------------------------ #


class BookNotAvailable(CirculationError):
    """
    Business rule 1: a student cannot borrow an unavailable book.

    Raised when every copy is out on loan.
    """

    message = "There are no copies of this book on the shelf at the moment."


class BookWithdrawn(BookNotAvailable):
    """
    A withdrawn book, which is unavailable for a different reason.

    Deliberately a subclass and not a sibling, so anything written to
    catch BookNotAvailable catches this too. Being withdrawn is one
    reason for being unavailable, not a separate kind of problem.
    """

    message = "This book is no longer part of the lending collection."


class AlreadyBorrowed(CirculationError):
    """
    Business rule 2: a student cannot borrow a book they already hold.

    The database enforces this as well, through the partial unique
    constraint one_active_loan_per_student_per_book, so this class is the
    readable half of a rule that is guaranteed either way.
    """

    message = "You already have this book out on loan."


class LoanLimitReached(CirculationError):
    """
    Business rule 3: a student may hold only so many books at once.

    This one cannot be a database constraint, because deciding it needs a
    count of the student's other loans and a constraint can only see the
    row in front of it. It is checked in services.py inside the same
    transaction and row lock as the loan it guards.
    """

    message = (
        f"You already have {rules.MAX_ACTIVE_LOANS} books out, which is the "
        f"most the library lends at one time. Return one to borrow another."
    )


class CopiesHeldForOthers(BookNotAvailable):
    """
    Every copy on the shelf is being held for somebody in the queue.

    A subclass of BookNotAvailable because, from this borrower's side,
    the book simply cannot be taken. Without this rule the reservation
    queue would be decoration: a passer by could walk off with the copy
    that had just been promised to the person who waited a fortnight for
    it.
    """

    message = (
        "The copies on the shelf are being held for students who reserved "
        "this book. Join the queue and you will be told when one is yours."
    )


# ------------------------------------------------------------------ #
# Returning and renewing                                             #
# ------------------------------------------------------------------ #


class AlreadyReturned(CirculationError):
    """
    The loan being returned or renewed has already come back.

    Most often a double submission: somebody presses Return, the page is
    slow, and they press it again. Refusing the second attempt is what
    stops the shelf count going up twice for one book.
    """

    message = "This book has already been returned."


class NotYourLoan(CirculationError):
    """
    A student tried to act on somebody else's loan.

    Business rule 5 is about being signed in at all, which the middleware
    handles. This is the next question after that one: being signed in
    does not make every loan in the library yours. A librarian is exempt,
    because processing other people's returns is their job.
    """

    message = "That loan belongs to another member."


class RenewalLimitReached(CirculationError):
    """A loan cannot be extended any further."""

    # Worded without a number so it reads correctly whether the cap is one
    # renewal or five. "renewed 1 times" is the sort of sentence that ends
    # up in a screenshot.
    message = (
        "This loan has already been renewed as many times as the library "
        "allows. Return the book, and borrow it again if nobody is waiting."
    )


class CannotRenewOverdue(CirculationError):
    """
    An overdue loan cannot be renewed.

    Otherwise renewal becomes a way to make a fine disappear: keep the
    book three weeks, renew, and the new due date is in the future so
    nothing is owed. The fine has to be settled by bringing the book
    back.
    """

    message = (
        "This loan is overdue, so it cannot be renewed. Please return the "
        "book and settle what is owed."
    )


class CannotRenewWithQueue(CirculationError):
    """
    Somebody is waiting for this book, so the loan cannot be extended.

    A queue that the person holding the book can outlast indefinitely is
    not a queue. This is the rule that makes the waiting list move.
    """

    message = (
        "Another member is waiting for this book, so the loan cannot be "
        "extended. It is due back on the date shown."
    )


# ------------------------------------------------------------------ #
# Reservations                                                       #
# ------------------------------------------------------------------ #


class CopiesAvailable(CirculationError):
    """
    There is no point reserving a book that is sitting on the shelf.

    Allowing it would mean a queue could form behind an available book,
    which makes the queue meaningless and confuses everyone in it.
    """

    message = (
        "This book is available now, so there is nothing to wait for. "
        "Borrow it instead."
    )


class AlreadyReserved(CirculationError):
    """
    The student is already in the queue for this book.

    Enforced in the database too, by the partial unique constraint
    one_active_reservation_per_student_per_book, which is restricted to
    the waiting and notified states so somebody whose earlier hold lapsed
    can join the queue again.
    """

    message = "You are already in the queue for this book."


class ReservationLimitReached(CirculationError):
    """A student may only hold so many places in queues at once."""

    message = (
        f"You are already waiting for {rules.MAX_ACTIVE_RESERVATIONS} books, "
        f"which is the most the library allows. Cancel one to join another "
        f"queue."
    )


class ReservationNotActive(CirculationError):
    """
    The reservation being cancelled has already ended.

    It was fulfilled, it expired, or it was cancelled once already, so
    there is nothing left to cancel.
    """

    message = "That reservation is no longer active."


class NotYourReservation(CirculationError):
    """A student tried to cancel somebody else's place in a queue."""

    message = "That reservation belongs to another member."


# ------------------------------------------------------------------ #
# Fines                                                              #
# ------------------------------------------------------------------ #


class NoFineOwed(CirculationError):
    """
    Nothing is owed on this loan, so there is nothing to mark as paid.

    Worth refusing rather than ignoring, because a fine marked paid when
    none was charged would leave an audit entry describing a payment that
    never happened.
    """

    message = "No fine is owed on this loan."


class FineAlreadyPaid(CirculationError):
    """
    This fine has already been settled.

    Refused so that two librarians clearing the same list cannot both
    record the same payment.
    """

    message = "This fine has already been marked as paid."


