"""
Authentication and membership views for the accounts app.
"""

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django_ratelimit.decorators import ratelimit

from .forms import LibraryAuthenticationForm, StudentRegistrationForm
from .models import User


@method_decorator(login_not_required, name="dispatch")
class RegisterView(CreateView):
    """
    Public student registration view.
    """

    model = User
    form_class = StudentRegistrationForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("accounts:login")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Your student account has been created successfully. You can now sign in.",
        )
        return response


@method_decorator(login_not_required, name="dispatch")
@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=False),
    name="dispatch",
)
@method_decorator(
    ratelimit(key="post:username", rate="5/m", method="POST", block=False),
    name="dispatch",
)
class LibraryLoginView(auth_views.LoginView):
    """
    Sign in view with rate limiting and styled credentials form.
    """

    form_class = LibraryAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class LibraryLogoutView(auth_views.LogoutView):
    """
    Sign out view. Redirects to catalogue shelf list.
    """

    next_page = "catalog:book_list"


@method_decorator(login_not_required, name="dispatch")
@method_decorator(
    ratelimit(key="ip", rate="5/m", method="POST", block=True),
    name="dispatch",
)
class PasswordResetRequestView(auth_views.PasswordResetView):
    """
    Rate-limited password reset request by email.
    """

    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
