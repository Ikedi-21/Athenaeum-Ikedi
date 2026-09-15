"""
URL patterns for the accounts app.

app_name below turns every name here into a namespaced one, so the login
page is reached as accounts:login rather than plain login. That is what
LOGIN_URL in settings.py expects, and it means an app added later cannot
collide with a name defined here.

The namespace has one consequence worth knowing about. Django's built in
password views default their success_url to unnamespaced names such as
password_change_done, which will not resolve here. Each one therefore has
its success_url supplied explicitly below.
"""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import manage_views, settings_views, views

app_name = "accounts"

urlpatterns = [
    # Joining, signing in and signing out.
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LibraryLoginView.as_view(), name="login"),
    path("logout/", views.LibraryLogoutView.as_view(), name="logout"),
    # Changing a password while signed in and knowing the current one.
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            success_url=reverse_lazy("accounts:password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    # Resetting a forgotten password by email. The request step is our own
    # subclass because it carries the rate limits; the remaining three are
    # Django's as shipped.
    path(
        "password/reset/",
        views.PasswordResetRequestView.as_view(),
        name="password_reset",
    ),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    # uidb64 identifies the account and token proves the link is genuine
    # and unused. Both come from the emailed link, so the pattern must
    # accept them in the order the email template writes them.
    path(
        "password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    # ---------------------------------------------------------------- #
    # Librarian: Student Member Directory                              #
    # ---------------------------------------------------------------- #
    path(
        "manage/students/",
        manage_views.StudentListView.as_view(),
        name="student_list",
    ),
    path(
        "manage/students/<int:pk>/",
        manage_views.StudentDetailView.as_view(),
        name="student_detail",
    ),
    # ---------------------------------------------------------------- #
    # Role-Based Settings & Legal Governance                           #
    # ---------------------------------------------------------------- #
    path("settings/", settings_views.SettingsView.as_view(), name="settings"),
    path("privacy/", settings_views.PrivacyPolicyView.as_view(), name="privacy"),
    path("terms/", settings_views.TermsOfServiceView.as_view(), name="terms"),
    path("security/", settings_views.SecurityOverviewView.as_view(), name="security"),
]
