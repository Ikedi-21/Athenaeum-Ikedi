"""
URL patterns for circulation, included from the root URLconf under /loans/.

The addresses are arranged so that the segment before a number says what
the number is. A loan id sits directly under the prefix, because /loans/12/
is a loan, while borrowing and reserving act on a book and so carry
books/ in front of theirs. Getting the two confused is the one mistake this
file can invite, and naming them is what prevents it.

Everything that changes state is POST only. Those views define no get
method, so Django answers a GET with 405 Method Not Allowed, which means no
crawler and no browser prefetching a link can borrow, return or renew
anything.

The desk pages live under desk/ and are all librarian only, which is
enforced by the mixin on each class rather than by the prefix. A URL prefix
is a naming convention and not a guard.
"""

from django.urls import path

from . import desk_views, views

app_name = "circulation"

urlpatterns = [
    # ---------------------------------------------------------------- #
    # What a member sees about their own borrowing                     #
    # ---------------------------------------------------------------- #
    #
    # The bare prefix, so /loans/ is the page a member means when they say
    # "my loans". Named loans rather than loan_list because it is written
    # out in templates far more often than it is read here.
    path("", views.LoanListView.as_view(), name="loans"),
    path("history/", views.LoanHistoryView.as_view(), name="history"),
    # ---------------------------------------------------------------- #
    # The five actions                                                 #
    # ---------------------------------------------------------------- #
    #
    # These two take a book id. Both are student only, and both carry a
    # rate limit, which lives on the view rather than here so that the
    # limit travels with the code it protects.
    path(
        "books/<int:pk>/borrow/",
        views.BorrowView.as_view(),
        name="borrow",
    ),
    path(
        "books/<int:pk>/reserve/",
        views.ReserveView.as_view(),
        name="reserve",
    ),
    # These two take a loan id and are open to the borrower or to a
    # librarian at the desk. Which of the two is asking is decided in
    # services.py, where the row can be seen.
    path("<int:pk>/renew/", views.RenewView.as_view(), name="renew"),
    #
    # return is a Python keyword, which matters not at all here: a URL name
    # is a string, and {% url 'circulation:return' %} is as valid as any
    # other. The alternative of calling it return_book would make every
    # template say something the library does not.
    path("<int:pk>/return/", views.ReturnView.as_view(), name="return"),
    # And this one takes a reservation id, hence its own segment.
    path(
        "reservations/<int:pk>/cancel/",
        views.CancelReservationView.as_view(),
        name="cancel_reservation",
    ),
    # ---------------------------------------------------------------- #
    # The desk                                                         #
    # ---------------------------------------------------------------- #
    path("desk/", desk_views.LoanDeskListView.as_view(), name="desk"),
    path("desk/fines/", desk_views.FineListView.as_view(), name="fines"),
    path(
        "desk/fines/<int:pk>/paid/",
        desk_views.MarkFinePaidView.as_view(),
        name="fine_paid",
    ),
]
