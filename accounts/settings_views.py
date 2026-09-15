"""
Settings views and enterprise configuration handlers for Athenaeum Ikedi.
Implements role-based tab architecture (User settings vs Librarian/Admin settings).
"""

import secrets
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from accounts.models import SystemConfig, User, UserSettings
from catalog.models import Book
from circulation.models import AuditLog, BorrowRecord


class SettingsView(LoginRequiredMixin, View):
    """
    Centralized role-based Settings hub.
    Accessible to all authenticated members for personal profile & security,
    with privileged enterprise management panels unlocked for librarians.
    """
    template_name = "accounts/settings.html"

    def get(self, request):
        user = request.user
        user_settings = user.user_settings
        system_config = SystemConfig.get_solo()

        # Active tab navigation
        active_tab = request.GET.get("tab", "profile").lower()
        admin_tabs = {"admin_users", "admin_config", "admin_audit", "admin_billing"}

        # Prevent non-librarians from reaching admin tabs
        if active_tab in admin_tabs and not user.is_librarian:
            messages.warning(request, "Access restricted: Administration tabs require Librarian privileges.")
            return redirect(f"{reverse('accounts:settings')}?tab=profile")

        context = {
            "active_tab": active_tab,
            "user_settings": user_settings,
            "system_config": system_config,
            "password_form": PasswordChangeForm(user=user),
        }

        # Context data for Admin tabs if user has librarian privileges
        if user.is_librarian:
            user_search = request.GET.get("user_q", "").strip()
            users_qs = User.objects.all().order_by("-date_joined")
            if user_search:
                users_qs = users_qs.filter(
                    Q(username__icontains=user_search)
                    | Q(first_name__icontains=user_search)
                    | Q(last_name__icontains=user_search)
                    | Q(email__icontains=user_search)
                )
            context["managed_users"] = users_qs[:50]
            context["user_search"] = user_search
            context["total_members_count"] = User.objects.count()
            context["active_members_count"] = User.objects.filter(is_active=True).count()
            context["students_count"] = User.objects.filter(role=User.Role.STUDENT).count()
            context["librarians_count"] = User.objects.filter(role=User.Role.LIBRARIAN).count()

            # Audit & forensic activity stream
            context["recent_audit_logs"] = AuditLog.objects.select_related("user").order_by("-timestamp")[:20]

            # System resource metrics
            context["catalogue_count"] = Book.objects.count()
            context["active_loans_count"] = BorrowRecord.objects.filter(returned_date__isnull=True).count()
            context["overdue_loans_count"] = BorrowRecord.objects.filter(
                returned_date__isnull=True, due_date__lt=timezone.localdate()
            ).count()

        # Mock / active device session information
        context["current_session"] = {
            "ip_address": request.META.get("REMOTE_ADDR", "127.0.0.1"),
            "user_agent": request.META.get("HTTP_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
            "session_key": request.session.session_key or "Active Session",
            "is_current": True,
        }

        return render(request, self.template_name, context)

    def post(self, request):
        action = request.POST.get("action", "").strip()
        user = request.user
        user_settings = user.user_settings

        # -------------------------------------------------------------- #
        # User Action: Update Profile                                    #
        # -------------------------------------------------------------- #
        if action == "update_profile":
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            email = request.POST.get("email", "").strip()
            bio = request.POST.get("bio", "").strip()
            phone_number = request.POST.get("phone_number", "").strip()

            if email:
                try:
                    validate_email(email)
                    # Check uniqueness across other users
                    if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                        messages.error(request, "This email address is already associated with another account.")
                        return redirect(f"{reverse('accounts:settings')}?tab=profile")
                    user.email = email
                except ValidationError:
                    messages.error(request, "Please provide a valid email address.")
                    return redirect(f"{reverse('accounts:settings')}?tab=profile")

            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=["first_name", "last_name", "email"])

            user_settings.bio = bio[:500]
            user_settings.phone_number = phone_number[:20]
            user_settings.save(update_fields=["bio", "phone_number"])

            messages.success(request, "Account profile updated successfully.")
            return redirect(f"{reverse('accounts:settings')}?tab=profile")

        # -------------------------------------------------------------- #
        # User Action: Change Password                                   #
        # -------------------------------------------------------------- #
        elif action == "change_password":
            form = PasswordChangeForm(user=user, data=request.POST)
            if form.is_valid():
                form.save()
                update_session_auth_hash(request, form.user)
                messages.success(request, "Your password has been changed securely.")
            else:
                error_messages = [f"{field}: {err[0]}" for field, err in form.errors.items()]
                messages.error(request, f"Password update failed: {', '.join(error_messages)}")
            return redirect(f"{reverse('accounts:settings')}?tab=security")

        # -------------------------------------------------------------- #
        # User Action: Notification Preferences                          #
        # -------------------------------------------------------------- #
        elif action == "update_notifications":
            user_settings.notify_email_loans = "notify_email_loans" in request.POST
            user_settings.notify_email_overdue = "notify_email_overdue" in request.POST
            digest_freq = request.POST.get("notify_email_digest", "daily")
            if digest_freq in {"none", "daily", "weekly"}:
                user_settings.notify_email_digest = digest_freq

            user_settings.save(update_fields=["notify_email_loans", "notify_email_overdue", "notify_email_digest"])
            messages.success(request, "Notification preferences updated.")
            return redirect(f"{reverse('accounts:settings')}?tab=notifications")

        # -------------------------------------------------------------- #
        # User Action: Display & Localization                            #
        # -------------------------------------------------------------- #
        elif action == "update_localization":
            theme = request.POST.get("theme", "light")
            timezone = request.POST.get("timezone", "Africa/Lagos")
            date_format = request.POST.get("date_format", "YYYY-MM-DD")

            if theme in {"light", "dark", "system"}:
                user_settings.theme = theme
            user_settings.timezone = timezone[:50]
            if date_format in {"YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"}:
                user_settings.date_format = date_format

            user_settings.save(update_fields=["theme", "timezone", "date_format"])
            messages.success(request, "Display and regional format preferences saved.")
            return redirect(f"{reverse('accounts:settings')}?tab=localization")

        # -------------------------------------------------------------- #
        # User Action: Toggle Multi-Factor Authentication                #
        # -------------------------------------------------------------- #
        elif action == "toggle_mfa":
            user_settings.mfa_enabled = not user_settings.mfa_enabled
            user_settings.save(update_fields=["mfa_enabled"])
            status = "enabled" if user_settings.mfa_enabled else "disabled"
            messages.success(request, f"Multi-Factor Authentication (MFA) has been {status}.")
            return redirect(f"{reverse('accounts:settings')}?tab=security")

        # ============================================================== #
        # Admin Actions (Strictly Guarded for Librarians)                #
        # ============================================================== #
        elif action.startswith("admin_"):
            if not user.is_librarian:
                return HttpResponseForbidden("Administrative privilege required.")

            system_config = SystemConfig.get_solo()

            # Admin: Toggle User Active Status
            if action == "admin_toggle_user_active":
                target_id = request.POST.get("target_user_id")
                target_user = get_object_or_404(User, pk=target_id)
                if target_user.pk == user.pk:
                    messages.error(request, "You cannot deactivate your own administrative account.")
                else:
                    target_user.is_active = not target_user.is_active
                    target_user.save(update_fields=["is_active"])
                    status = "activated" if target_user.is_active else "deactivated"
                    messages.success(request, f"Account '{target_user.username}' has been {status}.")
                return redirect(f"{reverse('accounts:settings')}?tab=admin_users")

            # Admin: Reassign User Role
            elif action == "admin_change_user_role":
                target_id = request.POST.get("target_user_id")
                new_role = request.POST.get("new_role")
                target_user = get_object_or_404(User, pk=target_id)
                if target_user.pk == user.pk:
                    messages.error(request, "You cannot alter your own administrative role.")
                elif new_role in {User.Role.STUDENT, User.Role.LIBRARIAN}:
                    target_user.role = new_role
                    target_user.save(update_fields=["role"])
                    messages.success(request, f"Role for '{target_user.username}' updated to {target_user.get_role_display()}.")
                return redirect(f"{reverse('accounts:settings')}?tab=admin_users")

            # Admin: Update Enterprise System Configuration
            elif action == "admin_update_system_config":
                try:
                    loan_days = int(request.POST.get("loan_duration_days", 14))
                    max_books = int(request.POST.get("max_books_per_student", 3))
                    fine_rate = float(request.POST.get("fine_rate_per_day", 50.0))
                    timeout_mins = int(request.POST.get("session_timeout_minutes", 60))
                except (ValueError, TypeError):
                    messages.error(request, "Invalid numeric input in configuration parameters.")
                    return redirect(f"{reverse('accounts:settings')}?tab=admin_config")

                system_config.loan_duration_days = max(1, loan_days)
                system_config.max_books_per_student = max(1, max_books)
                system_config.fine_rate_per_day = max(0.0, fine_rate)
                system_config.session_timeout_minutes = max(5, timeout_mins)
                system_config.allow_student_reservations = "allow_student_reservations" in request.POST
                system_config.maintenance_mode = "maintenance_mode" in request.POST
                system_config.webhook_url = request.POST.get("webhook_url", "").strip()

                system_config.save()
                messages.success(request, "Enterprise system configuration parameters updated.")
                return redirect(f"{reverse('accounts:settings')}?tab=admin_config")

            # Admin: Regenerate API Key
            elif action == "admin_regenerate_api_key":
                system_config.api_key_primary = f"ath_live_{secrets.token_hex(16)}"
                system_config.save(update_fields=["api_key_primary"])
                messages.success(request, "Primary institutional API Bearer key regenerated.")
                return redirect(f"{reverse('accounts:settings')}?tab=admin_config")

        # Fallback for unrecognized actions
        return redirect(reverse("accounts:settings"))


@method_decorator(login_not_required, name="dispatch")
class PrivacyPolicyView(TemplateView):
    template_name = "pages/privacy.html"


@method_decorator(login_not_required, name="dispatch")
class TermsOfServiceView(TemplateView):
    template_name = "pages/terms.html"


@method_decorator(login_not_required, name="dispatch")
class SecurityOverviewView(TemplateView):
    template_name = "pages/security.html"
