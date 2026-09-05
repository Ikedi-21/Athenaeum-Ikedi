"""
Authentication views: joining the library, signing in and signing out.

Django's own LoginView, LogoutView and the password change and reset views
do the work here, subclassed only where this project needs something
different. They already handle the parts that are easy to get subtly wrong:
cycling the session key on login so a stolen pre login session cannot be
reused, validating the safety of the next parameter so a crafted link
cannot bounce a freshly signed in user off to another site, and putting
the password fields on the sensitive parameter list so they never appear
in an error report.

Rate limiting is applied in non blocking mode throughout. django-ratelimit
raises Ratelimited by default, which subclasses PermissionDenied and so
produces a bare 403 page. Setting block=False instead leaves a flag on the
request and lets the view decide, which here means a readable message on
the form the person is already looking at.
"""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetView
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django_ratelimit.decorators import ratelimit

from .forms import LibraryAuthenticationForm, StudentRegistrationForm

# The limits live together at the top of the file so the numbers can be
# read and adjusted in one place instead of being buried in decorators.
#
# Login is limited two ways at once because the two attacks are different
# shapes. One machine working through a password list is caught by the
# address limit. A botnet trying the same handful of common passwords
# against one account arrives from many addresses, so the address limit
# never trips, but every attempt carries the same username and the second
# limit catches it. Both are needed; either alone leaves a gap.
LOGIN_ATTEMPTS_PER_ADDRESS = ratelimit(
    key="ip", rate="10/5m", method="POST", block=False
)
LOGIN_ATTEMPTS_PER_USERNAME = ratelimit(
    key="post:username", rate="5/5m", method="POST", block=False
)

# Registration is limited per address only, since there is no account name
# to key on yet. Five an hour is generous for a real person and stops a
# script filling the student table.
REGISTRATIONS_PER_ADDRESS = ratelimit(
    key="ip", rate="5/h", method="POST", block=False
)

# Password reset is limited on the submitted address as well as the
# connection, because the person being inconvenienced by a flood of reset
# mail is the account holder, not the sender. Keying on the address means
# a mistyped email is a fresh key and costs the real owner nothing, while
# repeated requests aimed at one mailbox are capped.
RESET_REQUESTS_PER_EMAIL = ratelimit(
    key="post:email", rate="5/h", method="POST", block=False
)
RESET_REQUESTS_PER_ADDRESS = ratelimit(
    key="ip", rate="15/h", method="POST", block=False
)


# login_not_required marks this view as an exception to the site wide
# LoginRequiredMiddleware. Without it the sign up page would itself demand
# a login, which nobody arriving here can provide.
@method_decorator(login_not_required, name="dispatch")
@method_decorator(REGISTRATIONS_PER_ADDRESS, name="post")
class RegisterView(CreateView):
    """
    Public sign up, which always produces a student account.

    A successful registration signs the new member straight in rather than
    sending them to the login page to type the same password again. The
    account was just created with a password this same request validated,
    so there is nothing further to prove.
    """

    form_class = StudentRegistrationForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("dashboard:home")

    def dispatch(self, request, *args, **kwargs):
        """
        Send anyone already signed in to their dashboard.

        Reaching this page while logged in means either a stale bookmark
        or a back button, and neither should end in a second account. The
        target is written out rather than taken from get_success_url,
        because that method reads self.object, which does not exist yet.
        """
        if request.user.is_authenticated:
            return redirect("dashboard:home")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """
        Refuse the submission when the address has hit its limit.

        CreateView.post sets self.object to None before doing anything
        else, and get_form below depends on that, so it is set here too
        for the early return path.
        """
        self.object = None
        if getattr(request, "limited", False):
            form = self.get_form()
            # add_error with a field name of None attaches the message to
            # the form as a whole, so it appears above the fields rather
            # than next to an arbitrary one.
            form.add_error(
                None,
                "Too many accounts have been created from this connection. "
                "Please try again later.",
            )
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """
        Save the account, then sign the new member in.

        super().form_valid saves the form and puts the new user on
        self.object, so it has to run first. login cycles the session key
        as it goes, which is what prevents a session fixation attack.
        """
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(
            self.request,
            f"Welcome to Athenaeum Ikedi, {self.object.first_name}. "
            "Your library account is ready.",
        )
        return response


# Both limits are stacked on the POST handler. The decorator ORs its
# result with whatever request.limited already held, so with two of them
# the flag is True if either limit has been reached.
@method_decorator(
    [LOGIN_ATTEMPTS_PER_ADDRESS, LOGIN_ATTEMPTS_PER_USERNAME], name="post"
)
class LibraryLoginView(LoginView):
    """
    Sign in.

    LoginView is already exempt from LoginRequiredMiddleware, so unlike
    RegisterView it needs no login_not_required of its own. The rate limit
    flag set by the decorators above is read by LibraryAuthenticationForm,
    which stops before calling authenticate so a throttled attempt is not
    also a free password guess.
    """

    template_name = "registration/login.html"
    authentication_form = LibraryAuthenticationForm

    # Someone already signed in has no use for this page. There is no
    # redirect loop risk because LOGIN_REDIRECT_URL points at the
    # dashboard, which never sends anyone back here.
    redirect_authenticated_user = True

    def form_valid(self, form):
        """Greet the member by name once the credentials check out."""
        user = form.get_user()
        messages.success(
            self.request,
            f"Signed in as {user.get_short_name() or user.get_username()}.",
        )
        return super().form_valid(form)


class LibraryLogoutView(LogoutView):
    """
    Sign out.

    Django accepts only POST here, which is deliberate on its part: a
    logout reachable by GET can be triggered by any image tag or link on
    another site, so every sign out control in the templates is a small
    form carrying a CSRF token.
    """

    def post(self, request, *args, **kwargs):
        """
        Log the person out, then leave a note saying so.

        The order looks wrong and is not. Logging out flushes the session,
        which would discard a message queued beforehand. The messages
        framework writes its queue to the session when the response passes
        back out through the middleware, which happens after this method
        returns, so a message added here still lands in the new session.
        """
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You have been signed out.")
        return response


@method_decorator(
    [RESET_REQUESTS_PER_ADDRESS, RESET_REQUESTS_PER_EMAIL], name="post"
)
class PasswordResetRequestView(PasswordResetView):
    """
    Start a password reset by emailing a signed, single use link.

    The success_url is stated here because Django's own default points at
    the unnamespaced pattern name password_reset_done, which does not exist
    in this project: accounts/urls.py declares an app_name, so every name
    it defines is reached as accounts:something.
    """

    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        """
        Send the email, unless the limit has been reached.

        A throttled request is not shown an error. It is quietly given the
        same redirect a real one gets, with no mail sent. That fits what
        this page already does on purpose: it never says whether an address
        belongs to an account, because that answer alone would let someone
        confirm who is a member. Returning a visible "rate limited" notice
        instead would create exactly the difference in behaviour the rest
        of the flow is careful to avoid.
        """
        if getattr(self.request, "limited", False):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)
