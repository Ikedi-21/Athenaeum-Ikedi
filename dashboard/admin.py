"""
Admin registration for the dashboard app.
"""

from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "message", "is_read", "created_date")
    list_filter = ("kind", "is_read", "created_date")
    search_fields = ("user__username", "message", "link")
    readonly_fields = ("created_date",)
