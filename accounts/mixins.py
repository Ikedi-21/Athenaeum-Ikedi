"""
The same role guards, in the form class based views can use.

Most views in this project are class based, and a decorator cannot be
applied to a class directly. Rather than wrap every view in
method_decorator, these two mixins are added to the class definition,
which reads better and puts the requirement in the most visible place.

Both are thin subclasses of Django's UserPassesTestMixin because that
class already produces exactly the behaviour wanted. Its dispatch calls
test_func and, when the test fails, calls AccessMixin.handle_no_permission,
which raises PermissionDenied for a signed in user and redirects to the
login page for an anonymous one. That is the same split the decorators in
decorators.py implement by hand, so the two approaches stay consistent.
"""

from django.contrib.auth.mixins import UserPassesTestMixin


class StudentRequiredMixin(UserPassesTestMixin):
    """
    Restrict a view to student accounts.

    Mix in before the view class so that dispatch runs the test first:
    class BorrowBookView(StudentRequiredMixin, View).
    """

    # AccessMixin reads this when raising PermissionDenied, so it becomes
    # the explanation on the 403 page.
    permission_denied_message = (
        "Only student accounts can borrow, return or review books."
    )

    def test_func(self):
        """
        Return True when the current user may see this view.

        The is_authenticated check is not redundant. test_func runs for
        anonymous visitors too, and AnonymousUser has no role field, so
        reading is_student on it would raise AttributeError instead of
        cleanly failing the test. Failing the test is what gets the
        visitor redirected to the login page.
        """
        user = self.request.user
        return user.is_authenticated and user.is_student


class LibrarianRequiredMixin(UserPassesTestMixin):
    """
    Restrict a view to librarian accounts.

    This is the class based half of business rule six: librarian only
    operations must be closed to ordinary students.
    """

    permission_denied_message = (
        "This page is part of library administration and is open to "
        "librarian accounts only."
    )

    def test_func(self):
        """
        Return True only for a signed in librarian.

        See the note in StudentRequiredMixin about why is_authenticated
        is tested first.
        """
        user = self.request.user
        return user.is_authenticated and user.is_librarian
