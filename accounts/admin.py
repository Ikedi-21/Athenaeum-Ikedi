"""
Admin interface registration for accounts and enterprise settings.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import SystemConfig, User, UserSettings


class UserSettingsInline(admin.StackedInline):
    model = UserSettings
    can_delete = False
    verbose_name_plural = "Settings"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (UserSettingsInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "is_staff",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Library & Permissions",
            {
                "fields": (
                    "role",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    search_fields = ("username", "first_name", "last_name", "email")


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = (
        "subscription_tier",
        "loan_duration_days",
        "max_books_per_student",
        "fine_rate_per_day",
        "maintenance_mode",
    )

    def has_add_permission(self, request):
        return False if SystemConfig.objects.exists() else True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "theme", "timezone", "notify_email_loans")
    search_fields = ("user__username", "user__email")
