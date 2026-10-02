"""
URL patterns for the dashboard app.
"""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("notifications/", views.notifications_list, name="notifications"),
    path(
        "notifications/<int:pk>/read/",
        views.mark_notification_read,
        name="notification_read",
    ),
    path(
        "notifications/read-all/",
        views.mark_all_notifications_read,
        name="notifications_read_all",
    ),
]
