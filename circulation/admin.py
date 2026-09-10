"""
Admin registration for circulation.

The admin is a maintenance tool here rather than the working interface. The
project has its own pages for borrowing, returning, renewing and settling a
fine, and those pages go through services.py, which is where the rules live.
Anything done here goes around them.

That is the whole reason the three classes below are shaped the way they
are. Where a hand edit would leave the library describing something
impossible, the field is shown and not offered. Where it would simply record
a correction, it stays editable, because a maintenance tool that cannot
correct anything is not one.

The audit log is read only in all three directions: it cannot be added to,
changed or deleted from here. A trail that can be quietly rewritten proves
nothing, which is also why AuditLog.save refuses a second write.
"""

from django.contrib import admin

from .models import AuditLog, BorrowRecord, Reservation


@admin.register(BorrowRecord)
class BorrowRecordAdmin(admin.ModelAdmin):
    """
    Loans, past and present.

    This exists to look things up and to correct the two figures a librarian
    can legitimately need to correct, a due date agreed as an extension at
    the desk and a fine adjusted by hand. It does not exist to lend or to
    accept a book back, and the restrictions below are what keep it honest
    about that.
    """

    list_display = (
        "book",
        "student",
        "borrowed_date",
        "due_date",
        "returned_date",
        "state",
        "fine_amount",
        "fine_paid",
    )

    # The four questions actually asked of this list: what is still out,
    # what money is outstanding, what was due when, and what came back when.
    list_filter = ("fine_paid", "due_date", "returned_date")

    # A loan is looked up by the book or by the person, so both are covered.
    # Following a relation with a double underscore is how the admin searches
    # a joined table.
    search_fields = (
        "book__title",
        "book__author",
        "student__username",
        "student__first_name",
        "student__last_name",
    )

    # Two columns follow a relation, so both are fetched in the same query
    # rather than one query per row.
    list_select_related = ("book", "student")

    # Dropdowns listing every book and every member would be the two
    # heaviest selects in the project. Autocomplete works because BookAdmin
    # and UserAdmin both define search_fields.
    autocomplete_fields = ("book", "student")

    # Browse by when the loan started, which is how a maintainer finds a
    # particular week.
    date_hierarchy = "borrowed_date"

    # borrowed_date is stamped once at creation, and returned_date is shown
    # rather than offered for a reason worth stating plainly: typing a date
    # into it would make the loan look closed while the copy stayed missing
    # from the shelf, no audit entry was written, and the next person in the
    # queue was never offered the book. return_book does those four things
    # together inside one transaction, and the desk page is how to reach it.
    #
    # due_date, fine_amount and fine_paid are all left editable, because
    # changing any of them corrects a figure without leaving another one
    # contradicting it.
    readonly_fields = ("borrowed_date", "returned_date")

    def has_add_permission(self, request):
        """
        Refuse to create a loan from here.

        A row added through this form would take a copy off the shelf in the
        records without taking it off the shelf in available_quantity, and
        nothing would have checked the loan cap, the withdrawn book guard or
        the copies held for other members. borrow_book does all of that in
        one transaction, so lending stays where the rules are.

        Test data belongs in a fixture or in the shell, both of which are
        deliberate acts rather than a form somebody wandered into.
        """
        return False

    @admin.display(description="State")
    def state(self, record):
        """
        Whether this loan is out, overdue or finished, in one column.

        Read from the model's own properties rather than worked out again
        here, so this cannot disagree with the pages that use them. No
        ordering= is set, because the answer is computed in Python and there
        is no column for the database to sort on.
        """
        if record.is_returned:
            return "Returned"
        if record.is_overdue:
            # Plural handled, since "1 days late" is the sort of thing that
            # ends up in a screenshot.
            days = record.days_overdue
            return f"{days} day{'' if days == 1 else 's'} late"
        return "On loan"


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    """
    The waiting lists, and where each place in them has got to.

    Adding is allowed here, unlike loans, because a reservation moves no
    copies: a row in the queue changes nothing on the shelf, so a hand
    written one leaves no figure contradicting another. What it does skip is
    the cap of three and the check that a copy is not already free, which is
    why the project's own reserve button is still the ordinary way in.
    """

    list_display = (
        "book",
        "student",
        "reserved_date",
        "status",
        "notified_date",
        "expires_date",
    )

    # The status is the only thing worth filtering on, and it is the thing
    # most often being looked for: everybody still waiting for one title.
    list_filter = ("status",)

    search_fields = (
        "book__title",
        "student__username",
        "student__first_name",
        "student__last_name",
    )

    list_select_related = ("book", "student")
    autocomplete_fields = ("book", "student")
    date_hierarchy = "reserved_date"

    # Stamped once when the place in the queue is taken.
    #
    # The other two dates stay editable, and status with them, so that a hold
    # stuck in the wrong state can be cleared by hand. One pairing to keep in
    # mind while doing that: a status of Copy available means nothing without
    # an expires_date beside it, because a hold with no expiry is one the
    # queue helpers in services.py will not count as holding a copy.
    readonly_fields = ("reserved_date",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """
    The trail, readable and nothing else.

    Registered rather than left out, because an audit log nobody can read is
    no more use than one nobody can trust. All three write permissions are
    refused below, which is what makes the detail page render as a plain
    read only view.

    The model refuses a second write of its own accord, so a change form
    reaching it would produce a server error rather than an edit. Turning the
    permission off here is what turns that crash into an interface that
    simply does not offer the button.
    """

    list_display = ("timestamp", "user", "action", "target", "ip_address")

    # Action first, because the usual question is "show me every deletion".
    # The date filter offers today and the last seven days.
    list_filter = ("action", "timestamp")

    # target holds a text snapshot such as "Book #12 Things Fall Apart", so
    # searching it finds everything that ever happened to one book even after
    # the book itself has been deleted. detail carries what changed, and the
    # username is there for "what did this account do".
    search_fields = ("target", "detail", "user__username")

    # One join for the user column instead of a query per row.
    list_select_related = ("user",)

    # An audit trail is read by date more than by anything else.
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        """
        Refuse to write an entry by hand.

        Entries are written by services.py and by the signals in signals.py,
        beside the action they describe. One typed in here would be a record
        of something that did not happen, which is the one thing a log must
        not contain.
        """
        return False

    def has_change_permission(self, request, obj=None):
        """
        Refuse to edit an entry.

        Returning False while leaving view permission alone is what makes
        Django render the detail page as a read only form, so an entry can
        still be opened and read in full.
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Refuse to remove an entry.

        Append only means append only. A log that can be pruned by whoever
        has most to gain from pruning it records nothing worth having.
        """
        return False
