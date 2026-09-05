"""
Dashboard views.

One view for now, the landing page a member sees after signing in. It is
the target of LOGIN_REDIRECT_URL, so it has to exist before a login can
complete. The real student panel, the librarian panel and the analytics
that go with them arrive with the dashboard task; what is here is the
role routing they will hang off, which is the part that will not change.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """
    Show the dashboard belonging to the signed in member's role.

    One URL serves both roles rather than sending students to one address
    and librarians to another. That keeps LOGIN_REDIRECT_URL, the navigation
    link and every bookmark identical for everybody, and it means a student
    cannot reach the librarian panel by typing its address, because the
    address does not exist: the role decides what is rendered.

    The login_required decorator is kept even though LoginRequiredMiddleware
    already guards the whole site. It costs one line and it means this view
    is still safe if it is ever called directly, from a test or from
    another view, where no middleware runs.
    """
    # Task nine replaces this single template with the two real panels and
    # the queries behind them. The role check is written out now so that
    # the shape of the view does not have to change then.
    context = {
        "is_librarian_view": request.user.is_librarian,
    }
    return render(request, "dashboard/home.html", context)
