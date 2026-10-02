"""
Role guards for function based views.

The assignment's sixth business rule is that librarian operations must be
protected from ordinary students, and these two decorators are how that
rule is enforced on every view that performs one.

Two different outcomes are deliberately produced here, because the two
situations are not the same problem. Somebody not signed in has simply
not proved who they are yet, so they are sent to the login page with a
next parameter that returns them to the page they wanted. Somebody who
is signed in but holds the wrong role has proved who they are and the
answer is still no, so they receive 403 Forbidden. Redirecting that
second person to the login page would be a confusing loop: they are
already logged in, so logging in again would change nothing.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _role_required(test, message):
    """
    Build a view decorator that admits only users passing the given test.

    The two decorators below differ in one line each, so the shared body
    lives here once. test receives the user object and returns True to
    allow the request. message is what the 403 page shows, which is worth
    writing carefully because it is the only explanation the person gets.
    """

    def decorator(view_func):
        # wraps copies the wrapped view's name, docstring and attributes
        # onto the wrapper. Without it, error pages and the URL resolver
        # would report every guarded view as "wrapper", and any flag set
        # on the view by another decorator would be lost.
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Checked first because the role test below would raise
            # AttributeError on AnonymousUser, which has no role field.
            # LoginRequiredMiddleware normally catches this case before
            # the view is ever reached, but the check stays here so the
            # decorator remains correct on its own, for example if the
            # middleware is removed or a view is called directly from a
            # test.
            if not request.user.is_authenticated:
                # get_full_path keeps the query string, so a filtered or
                # paginated URL survives the round trip through login.
                # redirect_to_login resolves settings.LOGIN_URL itself,
                # which is why the URL pattern name works there.
                return redirect_to_login(request.get_full_path())

            if not test(request.user):
                # Raising rather than redirecting hands control to
                # Django's 403 handler, so a single template can present
                # every refusal in the project the same way.
                raise PermissionDenied(message)

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


# Applied to borrowing, returning, renewing, reserving and reviewing.
# A librarian is refused on purpose rather than waved through: staff
# borrowing on their own account would sidestep the three loan cap and
# distort the analytics, and there is no requirement for them to do it.
student_required = _role_required(
    lambda user: user.is_student,
    "Only student accounts can borrow, return or review books.",
)


# Applied to adding, editing and withdrawing books, processing returns,
# settling fines, viewing the student list and reading the audit log.
librarian_required = _role_required(
    lambda user: user.is_librarian,
    "This page is part of library administration and is open to "
    "librarian accounts only.",
)
