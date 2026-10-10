"""
Views for the dashboard app: personal student hubs, institution librarian overviews,
and notification inbox management.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Notification
from .utils import get_librarian_dashboard_data, get_student_dashboard_data


@login_required
def home(request):
    """
    Central personalized dashboard router: delivers institutional overview
    to librarians and personal borrowing/queue metrics to students.
    """
    if request.user.is_librarian:
        context = get_librarian_dashboard_data()
        context["is_librarian_view"] = True
    else:
        context = get_student_dashboard_data(request.user)
        context["is_librarian_view"] = False

    return render(request, "dashboard/home.html", context)


@login_required
def notifications_list(request):
    """
    Paginated/complete listing of notifications for the current user.
    """
    notifications = Notification.objects.filter(user=request.user).order_by(
        "-created_date"
    )
    return render(
        request,
        "dashboard/notifications.html",
        {"notifications": notifications},
    )


@login_required
def mark_notification_read(request, pk):
    """
    Mark an individual alert as read, and optionally redirect to its target link.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])

    if notification.link:
        return redirect(notification.link)
    return redirect("dashboard:notifications")


@login_required
def mark_all_notifications_read(request):
    """
    Mark all unread notifications for the active user as read.
    """
    Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True
    )
    messages.success(request, "All notifications have been marked as read.")
    return redirect("dashboard:notifications")
