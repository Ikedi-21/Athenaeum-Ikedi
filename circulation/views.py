"""
The student's side of circulation: what I have out, and the buttons that
change it.

Every action here is a POST to a view that does almost nothing. It finds
the row, hands it to circulation.services, catches the one base exception
and turns it into a message. No rule is restated in this file, which is
the whole point of having services.py: the answer to "may this happen" is
the same whether a page asked it, the admin asked it or a test asked it.

Two of the five actions are restricted to students. Borrowing and
reserving are, because a librarian has no reason to do either. Returning,
renewing and cancelling a hold can each be done by the borrower or by a
librarian at the desk, and which of the two is asking changes nothing but
the audit entry, so the ownership question is left to the service, where
it can see the row it is being asked about.

No view in this file has a get method. Every one of them changes state,
and View.dispatch answers a GET with 405 when no handler exists, which
means a crawler following links, or a browser prefetching what it thinks
will be clicked next, cannot borrow a book by reading a page.
"""

from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView, TemplateView
from django_ratelimit.decorators import ratelimit

from accounts.mixins import StudentRequiredMixin
from catalog.models import Book

from . import rules, services
from .exceptions import CirculationError
from .models import BorrowRecord, Reservation, ReservationStatus

# Borrowing and reserving are limited per member rather than per address,
# because both require a signed in account and a student behind a shared
# campus connection should not be throttled by what the person next to
# them is doing.
#
# Neither limit is what stops a student taking too many books: the loan cap
# of three and the one live reservation per book rule do that, in
# services.py, where they can be tested. These exist for the other shape of
# abuse, a script posting the same button hundreds of times a minute, which
# costs a transaction and a row lock on every attempt even when every one
# of them is refused.
#
# block=False throughout, matching the accounts app, so the view still runs
# and can say something a person understands instead of returning a bare
# 403 page.
BORROW_ATTEMPTS_PER_MEMBER = ratelimit(
    key="user", rate="20/h", method="POST", block=False
)
RESERVATIONS_PER_MEMBER = ratelimit(
    key="user", rate="20/h", method="POST", block=False
)

# Said in one place so the two throttled paths cannot word it differently.
THROTTLED_MESSAGE = (
    "That is a lot of requests in a very short time. Wait a minute and "
    "try again."
)


def money(amount):
    """
    Write a fine the way it would be said out loud.

    Kept here rather than in a template filter because both this file and
    the desk views need it, and because a fine is a Decimal that must never
    reach a float on its way to being shown.
    """
    return f"{amount:.2f} naira"


def on_date(value):
    """
    Format a date without going through strftime.

    Django's own formatter is used because the obvious strftime pattern for
    an unpadded day number, %-d, is a GNU extension that raises on Windows,
    and this project is developed there.
    """
    return formats.date_format(value, "j F Y")


class CirculationActionView(View):
    """
    The shape shared by every button in this app.

    A POST arrives, one service is called, the outcome becomes a message,
    and the page the button was drawn on is loaded again. Subclasses supply
    only the middle step.
    """

    def redirect_target(self, request, fallback):
        """
        Where to send the browser once the work is done.

        Every button carries a hidden next field holding the page it was
        drawn on, so borrowing from a book page lands back on that book,
        renewing from the loans page lands back on the loans page, and one
        view can serve buttons on four different pages without knowing
        which one it was pressed from.

        The value is checked before it is used. It arrived in the request,
        and an unchecked redirect target is an open redirect: a crafted
        link could bounce a signed in member off to another site while
        appearing to come from this one. Anything that fails the check is
        dropped in favour of the caller's own fallback rather than being
        reported, because a member who typed nothing wrong has nothing to
        act on.
        """
        target = request.POST.get("next") or ""
        if target and url_has_allowed_host_and_scheme(
            url=target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return target
        return fallback

    def refuse_if_throttled(self, request, fallback):
        """
        Turn a tripped rate limit into a message and a redirect.

        Returns a response when the limit has been reached and None when it
        has not, so a caller reads as: if a refusal came back, return it.

        request.limited is set by the ratelimit decorator in non blocking
        mode. getattr with a default is needed because a view reached
        without the decorator, which is every action except borrowing and
        reserving, has no such attribute at all.
        """
        if getattr(request, "limited", False):
            messages.error(request, THROTTLED_MESSAGE)
            return redirect(self.redirect_target(request, fallback))
        return None


@method_decorator(BORROW_ATTEMPTS_PER_MEMBER, name="post")
class BorrowView(StudentRequiredMixin, CirculationActionView):
    """
    Take a book out. Rules 1 to 5 of the six all meet here.

    The book is looked up without filtering out withdrawn ones on purpose.
    A withdrawn book found and refused by name reads better than the same
    book vanishing into a 404, and borrow_book raises BookWithdrawn for
    exactly that.
    """

    def post(self, request, pk):
        """Ask for the loan, then say what happened either way."""
        book = get_object_or_404(Book, pk=pk)
        fallback = book.get_absolute_url()

        refusal = self.refuse_if_throttled(request, fallback)
        if refusal is not None:
            return refusal

        try:
            record = services.borrow_book(
                student=request.user, book=book, request=request
            )
        except CirculationError as exc:
            # str(exc) is the sentence the exception class carries, which
            # sits in exceptions.py beside the rule that raised it. Which
            # rule refused is therefore not something this view knows or
            # needs to know.
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"{record.book.title} is yours until "
                f"{on_date(record.due_date)}.",
            )
        return redirect(self.redirect_target(request, fallback))


@method_decorator(RESERVATIONS_PER_MEMBER, name="post")
class ReserveView(StudentRequiredMixin, CirculationActionView):
    """
    Join the queue for a book with no copy free.

    reserve_book refuses when a copy is in fact available, through
    CopiesAvailable, rather than quietly taking a reservation the student
    does not need. So the message on a refusal is often the useful one:
    go and borrow it.
    """

    def post(self, request, pk):
        """Join the queue, and say what place in it that turned out to be."""
        book = get_object_or_404(Book, pk=pk)
        fallback = book.get_absolute_url()

        refusal = self.refuse_if_throttled(request, fallback)
        if refusal is not None:
            return refusal

        try:
            reservation = services.reserve_book(
                student=request.user, book=book, request=request
            )
        except CirculationError as exc:
            messages.error(request, str(exc))
        else:
            # One extra COUNT query, which is what queue_position costs and
            # why it is a method rather than a property. Worth it once,
            # here, because a place in a queue is the only thing a student
            # actually wants to know at this moment.
            messages.success(
                request,
                f"You are number {reservation.queue_position()} in the "
                f"queue for {reservation.book.title}. A copy will be held "
                f"for {rules.RESERVATION_HOLD_DAYS} days when one comes "
                f"back.",
            )
        return redirect(self.redirect_target(request, fallback))


class RenewView(CirculationActionView):
    """
    Push a due date back, or be told why not.

    Open to any signed in member, not only students, because a librarian
    renewing a loan at the desk is ordinary work.

    The loan is fetched without filtering on the signed in member, which is
    deliberate and is not a missing guard. Filtering here would turn a
    librarian's legitimate renewal into a 404. Whether this particular loan
    belongs to whoever pressed the button is checked inside renew_loan,
    which raises NotYourLoan, because that question is about the row and
    only the service can see the row.
    """

    def post(self, request, pk):
        """Ask for the renewal, then report the new date or the refusal."""
        record = get_object_or_404(
            BorrowRecord.objects.select_related("book", "student"), pk=pk
        )
        fallback = reverse("circulation:loans")

        try:
            record = services.renew_loan(
                record=record, actor=request.user, request=request
            )
        except CirculationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"{record.book.title} is now due "
                f"{on_date(record.due_date)}.",
            )
        return redirect(self.redirect_target(request, fallback))


class ReturnView(CirculationActionView):
    """
    Bring a book back. Rule 4's other half.

    This one view serves two pages: a student returning their own loan from
    the loans page, and a librarian clearing a loan at the desk. Both do
    exactly the same thing to the same row, so there is one view, and
    return_book decides whose name goes in the audit entry from the actor
    it is handed.

    As with renewing, the row is not filtered by member and the ownership
    check lives in the service, which raises NotYourLoan for a student
    aiming at somebody else's loan.
    """

    def post(self, request, pk):
        """Take the book back, then say what it cost if anything."""
        record = get_object_or_404(
            BorrowRecord.objects.select_related("book", "student"), pk=pk
        )
        fallback = reverse("circulation:loans")

        try:
            record = services.return_book(
                record=record, actor=request.user, request=request
            )
        except CirculationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, self.outcome(request, record))
        return redirect(self.redirect_target(request, fallback))

    def outcome(self, request, record):
        """
        The sentence a successful return produces.

        Built in a method rather than inline because it varies two ways at
        once, and nesting those two branches in the middle of post would
        bury what the view actually does.

        Whose loan it was, because a librarian working through the desk list
        needs to see which member each row belonged to, while a student
        already knows. And whether anything is owed, because return_book
        freezes the fine on the record and a figure nobody mentions is a
        figure nobody pays.
        """
        if request.user == record.student:
            opening = f"{record.book.title} is back"
        else:
            borrower = (
                record.student.get_full_name()
                or record.student.get_username()
            )
            opening = f"{record.book.title} is back from {borrower}"

        # Not record.days_overdue, which is defined to return zero once a
        # book is back: while a book is out that figure is live, and the
        # moment it returns the frozen fine becomes the fact instead. So the
        # count of late days is worked out again from the two dates, by the
        # same function that produced the fine.
        late = rules.days_late(
            record.due_date, timezone.localdate(record.returned_date)
        )

        # Decimal, compared against a Decimal. A fine of zero is the normal
        # case and saying nothing about it is the right amount to say.
        if record.fine_amount > Decimal("0.00"):
            return (
                f"{opening}, {late} day{'' if late == 1 else 's'} late. "
                f"{money(record.fine_amount)} is owed, payable at the desk."
            )
        return f"{opening}, thank you."


class CancelReservationView(CirculationActionView):
    """
    Leave a queue.

    The row is not deleted. cancel_reservation marks it cancelled, which is
    what lets the same student join the same queue again later, since the
    unique constraint on the pair only covers the two live states.

    Open to librarians as well as the holder, because a hold sometimes has
    to be cleared at the desk, and NotYourReservation in the service is
    what stops one student cancelling another's place.
    """

    def post(self, request, pk):
        """Give up the place, then confirm which queue was left."""
        reservation = get_object_or_404(
            Reservation.objects.select_related("book", "student"), pk=pk
        )
        fallback = reverse("circulation:loans")

        try:
            reservation = services.cancel_reservation(
                reservation=reservation, actor=request.user, request=request
            )
        except CirculationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"You have left the queue for "
                f"{reservation.book.title}.",
            )
        return redirect(self.redirect_target(request, fallback))


def unpaid_fines(student):
    """
    The loans this student still owes money on.

    A fine has no table of its own: it is frozen onto the loan that
    produced it when the book comes back, so anything owed is a returned
    loan with an amount on it that nobody has ticked as settled.

    Both conditions are needed. A settled fine keeps its amount rather
    than being zeroed, which is what lets a librarian look back at what
    was charged, so the amount alone does not say whether it is still due.
    """
    return BorrowRecord.objects.filter(
        student=student,
        fine_paid=False,
        fine_amount__gt=Decimal("0.00"),
    )


def fine_total(student):
    """
    What this student owes altogether, as a Decimal.

    Sum returns None rather than zero when there is nothing to add up, so
    the None is turned into a Decimal here and every caller can print the
    figure without checking it first.
    """
    owed = unpaid_fines(student).aggregate(total=Sum("fine_amount"))["total"]
    return owed or Decimal("0.00")


class LoanListView(StudentRequiredMixin, TemplateView):
    """
    What a student has out at this moment, and what they are waiting for.

    A TemplateView rather than a ListView, because the page shows three
    unrelated lists at once. A ListView would have to nominate one of them
    as the object_list and fetch the other two in get_context_data anyway,
    which is the same work under a name that misdescribes it.

    Nothing here is paginated and nothing needs to be. The loan cap of
    three and the reservation cap of three are what bound this page, so it
    cannot grow past six rows however long somebody has been a member.
    History is the part that grows, and history has its own page below.
    """

    template_name = "circulation/loan_list.html"

    def get_context_data(self, **kwargs):
        """
        The lists, the caps they are measured against, and anything owed.

        setdefault throughout, so that a subclass or a test can pass any of
        these in and have its own value survive.
        """
        student = self.request.user

        # Soonest due first, which is the order a student needs to act in.
        # Meta.ordering on BorrowRecord is newest borrowed first: right for
        # a history table, wrong here, so it is overridden rather than
        # inherited.
        kwargs.setdefault(
            "loans",
            services.active_loans(student)
            .select_related("book")
            .order_by("due_date"),
        )

        # Both caps, so the template can say "2 of 3" instead of a bare
        # count that means nothing without the limit beside it. Read from
        # rules.py rather than written here, because a page quoting its own
        # figure is a page that will eventually quote the wrong one.
        kwargs.setdefault("loan_cap", rules.MAX_ACTIVE_LOANS)
        kwargs.setdefault("reservation_cap", rules.MAX_ACTIVE_RESERVATIONS)
        kwargs.setdefault("hold_days", rules.RESERVATION_HOLD_DAYS)
        kwargs.setdefault("fine_per_day", rules.FINE_PER_DAY)
        kwargs.setdefault("fine_total", fine_total(student))

        # setdefault here too, one key at a time, so the queue entries follow
        # the same rule as everything above them and none of them can
        # quietly replace a value a caller supplied.
        for name, value in self.queues(student).items():
            kwargs.setdefault(name, value)
        return super().get_context_data(**kwargs)

    def queues(self, student):
        """
        Split the student's live reservations into the three things they
        can actually mean.

        holds are reservations with a copy on the shelf waiting to be
        collected. waiting are places in a queue with nothing to collect
        yet. lapsed are holds whose collection window has run out but which
        no borrow or reserve has swept into EXPIRED yet, since that sweep
        is triggered by somebody acting on the title rather than by a clock.

        One query, split in Python. The reservation cap of three bounds the
        result, so three filtered queries against the same handful of rows
        would cost two extra round trips to save nothing.

        A dict rather than three return values, because get_context_data
        wants names anyway and unpacking a triple by position is how the
        wrong list ends up under the right heading.
        """
        reservations = list(
            services.active_reservations(student).select_related("book")
        )

        # has_expired is a property on the model, computed from the stored
        # expires_date, so reading it here writes nothing. That matters:
        # this runs during a GET, and a page that quietly changed rows
        # while being looked at would not be safe to refresh.
        holds = [
            r
            for r in reservations
            if r.status == ReservationStatus.NOTIFIED and not r.has_expired
        ]
        lapsed = [r for r in reservations if r.has_expired]
        waiting = [
            r for r in reservations if r.status == ReservationStatus.WAITING
        ]

        # The three lists, plus the one number the heading needs. Counted
        # from the whole list rather than by adding the three lengths in a
        # template, and counting all three because all three are what the
        # cap of three counts: a lapsed hold still occupies a place until
        # somebody acts on that title and the sweep retires it.
        return {
            "holds": holds,
            "lapsed": lapsed,
            "waiting": waiting,
            "reservation_count": len(reservations),
        }


class LoanHistoryView(StudentRequiredMixin, ListView):
    """
    Everything this student has borrowed and brought back.

    A ListView here, and paginated, because this is the one page in the app
    with no cap on it. The loans page opposite is bounded at six rows by
    the two caps in rules.py; a member of three years has as many rows here
    as books they have read.
    """

    template_name = "circulation/loan_history.html"
    context_object_name = "loans"

    # Ten, where the catalogue uses twelve. That number is a grid of cards
    # three or four across and wants to divide evenly; this is a table of
    # one row per loan, where a round ten reads better.
    paginate_by = 10

    def get_queryset(self):
        """
        This student's returned loans, most recently returned first.

        Filtered on the signed in member, which is the whole guard this
        page needs. There is no pk in the URL, so there is no row to aim at
        and nothing another member could reach by editing an address.

        Ordered by returned_date rather than the borrowed_date that
        Meta.ordering would use, because the question a history page
        answers is what happened lately, and a book borrowed in March and
        brought back in June belongs beside June.
        """
        return (
            BorrowRecord.objects.filter(
                student=self.request.user,
                returned_date__isnull=False,
            )
            .select_related("book")
            .order_by("-returned_date")
        )

    def get_context_data(self, **kwargs):
        """
        The fines panel, which is about every unpaid loan and not only the
        ones on the page being looked at.

        Built from unpaid_fines and fine_total rather than from object_list,
        because a balance worked out from one page of results would show a
        different figure on page two, and a total that changes as you turn
        the page is worse than no total at all.
        """
        student = self.request.user
        kwargs.setdefault(
            "fines",
            unpaid_fines(student)
            .select_related("book")
            .order_by("-returned_date"),
        )
        kwargs.setdefault("fine_total", fine_total(student))
        kwargs.setdefault("fine_per_day", rules.FINE_PER_DAY)
        return super().get_context_data(**kwargs)
