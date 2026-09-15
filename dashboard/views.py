"""
Dashboard views.

The central command hubs for Athenaeum Ikedi:
- Role-routed dashboard home (student view vs librarian view)
- Notification management (list, mark single read, mark all read)
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notification
from .utils import get_librarian_dashboard_data, get_student_dashboard_data


def _safe_redirect(request, fallback="dashboard:home"):
    """Safely return to previous page or default fallback."""
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback)


@login_required
def home(request):
    """
    Render either the student dashboard or the librarian dashboard based on role.
    """
    user = request.user
    context = {
        "is_librarian_view": user.is_librarian,
    }

    if user.is_librarian:
        librarian_data = get_librarian_dashboard_data()
        context.update(librarian_data)
        return render(request, "dashboard/home.html", context)
    else:
        student_data = get_student_dashboard_data(user)
        context.update(student_data)
        return render(request, "dashboard/home.html", context)


@login_required
def notifications_list(request):
    """
    Show all notifications for the current signed-in user with pagination and filter.
    """
    filter_type = request.GET.get("filter", "all")
    notifications_qs = Notification.objects.filter(user=request.user)

    if filter_type == "unread":
        notifications_qs = notifications_qs.filter(is_read=False)

    paginator = Paginator(notifications_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    unread_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()

    context = {
        "page_obj": page_obj,
        "filter_type": filter_type,
        "unread_count": unread_count,
    }
    return render(request, "dashboard/notifications.html", context)


@login_required
@require_POST
def mark_notification_read(request, pk):
    """
    Mark a single notification as read.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.mark_read()
    return _safe_redirect(request, fallback="dashboard:notifications")


@login_required
@require_POST
def mark_all_notifications_read(request):
    """
    Mark every unread notification for the signed-in user as read.
    """
    updated_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).update(is_read=True)
    if updated_count:
        messages.success(
            request, f"Marked {updated_count} notification(s) as read."
        )
    return _safe_redirect(request, fallback="dashboard:notifications")
