"""
Admin interface registration for circulation: loans, holds, and audit logging.
"""

from django.contrib import admin
from .models import AuditLog, BorrowRecord, Reservation


@admin.register(BorrowRecord)
class BorrowRecordAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "student",
        "borrowed_date",
        "due_date",
        "returned_date",
        "fine_amount",
        "fine_paid",
    )
    list_filter = ("fine_paid", "returned_date", "borrowed_date")
    search_fields = ("book__title", "student__username", "student__email")
    readonly_fields = ("borrowed_date",)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "student",
        "status",
        "reserved_date",
        "notified_date",
        "expires_date",
    )
    list_filter = ("status", "reserved_date")
    search_fields = ("book__title", "student__username")
    readonly_fields = ("reserved_date",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "user", "target", "ip_address")
    list_filter = ("action", "timestamp")
    search_fields = ("target", "detail", "user__username")
    readonly_fields = ("timestamp", "user", "action", "target", "detail", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
