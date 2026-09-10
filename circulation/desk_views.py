"""
The librarian's side of circulation: the loan desk and the fines list.

Separate from views.py for the same reason catalog splits manage_views.py
away from views.py. The two files have different readers. One is a member
looking at their own borrowing, bounded at six rows and needing no search;
this one is somebody working through every loan in the library, needing a
search box, a filter and pagination, and it must never be reachable by a
student.

Every class here is behind LibrarianRequiredMixin, which sends a signed out
visitor to the login page and answers a signed in student with a 403.

The buttons drawn on these pages mostly post to views.py rather than to
anything here, because returning and renewing a loan are the same two
operations whoever presses them: return_book and renew_loan already exempt
a librarian from the ownership check and already decide whose name the
audit entry carries. Only marking a fine settled is desk work with no
student equivalent, so only that one has a view of its own below.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import ListView

from accounts.mixins import LibrarianRequiredMixin

from . import rules, services
from .exceptions import CirculationError
from .models import BorrowRecord
from .views import CirculationActionView, money

# The loan desk filter, written as data in the manner of SORT_OPTIONS in
# catalog/views.py, so that adding a state is a new entry here rather than
# another branch inside a method.
#
# Each entry holds a callable rather than a ready made Q object, and the
# reason is timing. A Q built at import time would capture the date the
# server started, so a process left running overnight would still be
# comparing against yesterday and would call an overdue book current. Taking
# today as an argument means the comparison is built fresh on every request.
LOAN_STATES = {
    "out": {
        "label": "Everything on loan",
        # An empty Q is the identity for filtering: anded with the rest it
        # changes nothing, which is how "no extra condition" is expressed
        # without the calling code needing a special case for it.
        "condition": lambda today: Q(),
    },
    "overdue": {
        "label": "Overdue",
        # Strictly earlier than today, because a book due today is not late
        # yet. This is the same boundary rules.days_late uses, which is what
        # keeps the list and the fine agreeing about what "late" means.
        "condition": lambda today: Q(due_date__lt=today),
    },
    "due_soon": {
        "label": f"Due within {rules.DUE_SOON_DAYS} days",
        # Both ends stated. Without the lower bound an overdue book would
        # also answer this filter, and the point of the two states is to
        # separate the books that need chasing from the ones that do not.
        "condition": lambda today: Q(
            due_date__gte=today,
            due_date__lte=today + timedelta(days=rules.DUE_SOON_DAYS),
        ),
    },
}

# Used when the query string says nothing and when it says something this
# module does not recognise. A filter is a preference rather than an
# address, so an unknown value falls back rather than raising.
DEFAULT_LOAN_STATE = "out"

# The fines filter. Plain Q objects rather than the callables above,
# because none of these three conditions depends on today's date, so there
# is nothing to go stale in a long running process.
FINE_STATES = {
    "owing": {
        "label": "Still owed",
        "condition": Q(fine_paid=False),
    },
    "settled": {
        "label": "Settled",
        "condition": Q(fine_paid=True),
    },
    "all": {
        "label": "Every fine charged",
        "condition": Q(),
    },
}

# The list opens on the money that is still outstanding, because that is
# what somebody visiting this page came to do something about.
DEFAULT_FINE_STATE = "owing"


class LoanDeskListView(LibrarianRequiredMixin, ListView):
    """
    Every copy the library currently has out, with a search box, a filter,
    and a return or renew button on each row.

    This is the page a librarian works from, and it answers two questions
    at once: which books are late, and where is the copy that the reader
    standing at the desk is asking about.

    Returned loans are deliberately not here. A desk list mixing live loans
    with years of settled history would bury the rows worth acting on, and
    the money left behind by a returned loan has its own page below.
    """

    model = BorrowRecord
    template_name = "circulation/loan_desk_admin.html"
    context_object_name = "loans"

    # Twenty, where the catalogue uses twelve. That number is a grid of
    # cards and wants to divide evenly into columns; this is a table, where
    # a longer page means less paging through a queue of people waiting.
    paginate_by = 20

    def get_search_term(self):
        """Whatever was typed into the search box, or an empty string."""
        return self.request.GET.get("q", "").strip()

    def get_state(self):
        """
        The chosen filter, checked against LOAN_STATES.

        Anything unrecognised becomes the default rather than an error,
        since a filter in a query string is a preference and not the
        address of anything: a stale bookmark naming a state that no longer
        exists is better answered with the whole list than with a 404.

        Checking against the table is also what keeps the query string out
        of the database. Only a key that appears in LOAN_STATES is ever
        looked up, so nothing a visitor types reaches a filter directly.
        """
        state = self.request.GET.get("state", DEFAULT_LOAN_STATE)
        return state if state in LOAN_STATES else DEFAULT_LOAN_STATE

    def search_filter(self, term):
        """
        Where the search box looks: the book, or the person holding it.

        A librarian at a desk has one of two things in front of them, a book
        or a member, so both have to be findable from the same box rather
        than from two. Title and author cover the book. Username, both name
        fields and the email address cover the member, because a name is
        what gets said out loud while a username is what is printed on the
        card, and either might be what somebody has to hand.

        icontains throughout, so a match is case insensitive and does not
        need the whole word. As in the catalogue search, the words are not
        split apart, so word order matters.
        """
        return (
            Q(book__title__icontains=term)
            | Q(book__author__icontains=term)
            | Q(student__username__icontains=term)
            | Q(student__first_name__icontains=term)
            | Q(student__last_name__icontains=term)
            | Q(student__email__icontains=term)
        )

    def get_queryset(self):
        """
        Live loans, narrowed by the filter and the search box, most urgent
        first.

        select_related pulls the book and the member into the same query.
        Every row prints a title and a name, so without it a page of twenty
        rows would cost forty extra queries, which is the N plus 1 problem
        in its most ordinary form.

        Ordered by due date rather than by the newest borrowed ordering that
        BorrowRecord.Meta would supply, because the first row of a desk list
        should be the loan most in need of attention. pk settles any tie, so
        two loans due on the same day cannot swap sides between page one and
        page two and drop a row out of a list it never left.
        """
        today = rules.today()

        queryset = (
            BorrowRecord.objects.filter(returned_date__isnull=True)
            .select_related("book", "student")
            .filter(LOAN_STATES[self.get_state()]["condition"](today))
        )

        term = self.get_search_term()
        if term:
            queryset = queryset.filter(self.search_filter(term))

        return queryset.order_by("due_date", "pk")

    def get_context_data(self, **kwargs):
        """
        The filter tabs, what was searched for, and the counts beside them.

        The counts are of the whole library and not of the filtered page,
        which is the point of them: a tab reading Overdue 4 has to say four
        whether or not the overdue tab is the one currently selected.

        Both numbers come from one aggregate over one scan. Count with a
        filter argument counts only the rows matching it, so two questions
        are answered by one round trip instead of two.
        """
        today = rules.today()
        totals = BorrowRecord.objects.filter(
            returned_date__isnull=True
        ).aggregate(
            out=Count("pk"),
            overdue=Count("pk", filter=Q(due_date__lt=today)),
        )

        # Built here rather than in the template, because a template cannot
        # iterate a dict of dicts and mark one entry as the selected one
        # without a filter tag written specially for it.
        state = self.get_state()
        kwargs.setdefault(
            "states",
            [
                {
                    "key": key,
                    "label": option["label"],
                    "selected": key == state,
                }
                for key, option in LOAN_STATES.items()
            ],
        )

        kwargs.setdefault("state", state)
        kwargs.setdefault("search_term", self.get_search_term())
        kwargs.setdefault("total_out", totals["out"])
        kwargs.setdefault("total_overdue", totals["overdue"])
        kwargs.setdefault("fine_per_day", rules.FINE_PER_DAY)
        return super().get_context_data(**kwargs)


class FineListView(LibrarianRequiredMixin, ListView):
    """
    Every fine the library has charged, and a button to settle each one.

    A fine has no table of its own. It is frozen onto the loan that produced
    it at the moment the book comes back, which is why this list is a list of
    returned loans with an amount above zero rather than a list of some
    separate Fine model.

    A settled fine keeps its amount rather than being zeroed, so this page
    can show what was charged as well as what is still owed, and the filter
    across the top is what chooses between those two readings.
    """

    model = BorrowRecord
    template_name = "circulation/fine_list_admin.html"
    context_object_name = "fines"
    paginate_by = 20

    def get_search_term(self):
        """Whatever was typed into the search box, or an empty string."""
        return self.request.GET.get("q", "").strip()

    def get_state(self):
        """
        The chosen filter, checked against FINE_STATES.

        Unrecognised values fall back to the default for the same reason
        they do on the loan desk, and the same check is what keeps anything
        typed into the query string from reaching a filter.
        """
        state = self.request.GET.get("state", DEFAULT_FINE_STATE)
        return state if state in FINE_STATES else DEFAULT_FINE_STATE

    def search_filter(self, term):
        """
        Where the search box looks on this page: the member, or the book.

        The same six places as the loan desk. Written out again rather than
        imported from that class, because the two lists sit side by side in
        one file and a shared method here would make each of them depend on
        the other's idea of what a search means. If a third page ever wants
        the same six, that is the moment to lift it out into one function.
        """
        return (
            Q(student__username__icontains=term)
            | Q(student__first_name__icontains=term)
            | Q(student__last_name__icontains=term)
            | Q(student__email__icontains=term)
            | Q(book__title__icontains=term)
            | Q(book__author__icontains=term)
        )

    def get_queryset(self):
        """
        Loans carrying a fine, narrowed by the filter and the search box.

        The base condition is an amount above zero. Comparing against a
        Decimal rather than a plain zero keeps the whole calculation in one
        numeric type, which is the same reason fine_amount is a
        DecimalField and not a FloatField.

        Ordered by returned_date descending, so the most recent charge is
        the first row: a fine somebody is about to come in and settle is
        almost always a recent one. pk settles ties, so a page boundary
        cannot lose a row.
        """
        queryset = (
            BorrowRecord.objects.filter(fine_amount__gt=Decimal("0.00"))
            .select_related("book", "student")
            .filter(FINE_STATES[self.get_state()]["condition"])
        )

        term = self.get_search_term()
        if term:
            queryset = queryset.filter(self.search_filter(term))

        return queryset.order_by("-returned_date", "pk")

    def get_context_data(self, **kwargs):
        """
        The filter tabs and the two figures the heading needs.

        Both figures describe every fine in the library rather than the page
        being looked at, because a total worked out from one page would read
        differently on page two, and a balance that changes as you turn the
        page is worse than no balance at all.

        Sum returns None when there is nothing to add up, so it is turned
        into a Decimal here and the template can print it without asking.
        """
        owing = BorrowRecord.objects.filter(
            fine_paid=False,
            fine_amount__gt=Decimal("0.00"),
        ).aggregate(total=Sum("fine_amount"), rows=Count("pk"))

        state = self.get_state()
        kwargs.setdefault(
            "states",
            [
                {
                    "key": key,
                    "label": option["label"],
                    "selected": key == state,
                }
                for key, option in FINE_STATES.items()
            ],
        )

        kwargs.setdefault("state", state)
        kwargs.setdefault("search_term", self.get_search_term())
        kwargs.setdefault("total_owed", owing["total"] or Decimal("0.00"))
        kwargs.setdefault("total_owing_rows", owing["rows"])
        kwargs.setdefault("fine_per_day", rules.FINE_PER_DAY)
        return super().get_context_data(**kwargs)


class MarkFinePaidView(LibrarianRequiredMixin, CirculationActionView):
    """
    Write down that a fine has been settled.

    The only action in this file with a view of its own, because it is the
    only one with no student equivalent: returning and renewing are shared
    with the member's own page and live in views.py.

    CirculationActionView is inherited for its two helpers, the checked
    redirect target and the throttle reply. Inheriting across the file
    boundary is safe here in a way it would not be in the catalogue, because
    nothing in views.py carries login_not_required: the guard on this class
    is LibrarianRequiredMixin and nothing in the parent can loosen it.

    No get method, so Django answers a GET with 405. Money changing hands is
    not something a link should be able to record.
    """

    def post(self, request, pk):
        """Mark it settled, then say what was settled and for whom."""
        record = get_object_or_404(
            BorrowRecord.objects.select_related("book", "student"), pk=pk
        )
        fallback = reverse("circulation:fines")

        try:
            record = services.mark_fine_paid(
                record=record, actor=request.user, request=request
            )
        except CirculationError as exc:
            # NoFineOwed and FineAlreadyPaid both land here, and both carry
            # their own sentence. A second press of the same button is
            # therefore refused with an explanation rather than recording a
            # payment twice.
            messages.error(request, str(exc))
        else:
            borrower = (
                record.student.get_full_name()
                or record.student.get_username()
            )
            messages.success(
                request,
                f"{money(record.fine_amount)} from {borrower} for "
                f"{record.book.title} is recorded as settled.",
            )
        return redirect(self.redirect_target(request, fallback))
