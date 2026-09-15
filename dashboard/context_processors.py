"""
Context processors for the dashboard app.

Supplies notification metrics to base templates so the navigation bar
can display live unread badges and quick alerts without each view
needing to query for them.
"""

from dashboard.models import Notification


def notification_context(request):
    """
    Expose unread notification count to templates.
    """
    if not request.user.is_authenticated:
        return {
            "unread_notification_count": 0,
            "navbar_notifications": [],
        }

    unread_notifications = list(
        Notification.objects.filter(
            user=request.user,
            is_read=False,
        )[:5]
    )

    return {
        "unread_notification_count": Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
        "navbar_notifications": unread_notifications,
    }


def theme_context(request):
    """
    Expose the authenticated user's theme preference to every template.

    The value is one of 'light', 'dark', or 'system'. base.html uses it
    to set data-theme on the <html> element, and the client-side theme
    engine reads that attribute to apply or resolve the correct palette.
    """
    if request.user.is_authenticated:
        return {"user_theme": request.user.user_settings.theme}
    return {"user_theme": "light"}
