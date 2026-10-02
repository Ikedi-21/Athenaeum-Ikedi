"""
Dashboard query utilities.

Provides aggregated and context-ready metrics for both the student
and librarian dashboard views, keeping views thin and logic testable.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from accounts.models import User
from catalog.models import Book, Category
from circulation import rules
from circulation.models import (
    AuditLog,
    BorrowRecord,
    Reservation,
    ReservationStatus,
)
from dashboard.models import Notification


def get_student_dashboard_data(student):
    """
    Gather everything a student needs on their main dashboard:
    - Active loans with due date urgency calculations
    - Active reservations (ready holds and queue status)
    - Unpaid fines overview
    - Unread notifications
    - Summary metrics
    """
    today = timezone.localdate()

    # Active loans
    active_loans = list(
        BorrowRecord.objects.filter(
            student=student,
            returned_date__isnull=True,
        )
        .select_related("book", "book__category")
        .order_by("due_date")
    )

    # Compute status flags for each active loan
    for loan in active_loans:
        loan.days_until_due = (loan.due_date - today).days
        loan.is_late = loan.due_date < today
        loan.is_due_soon = 0 <= loan.days_until_due <= rules.DUE_SOON_DAYS
        if loan.is_late:
            loan.overdue_days = rules.days_late(loan.due_date, today)
            loan.estimated_fine = rules.fine_for(loan.due_date, today)
        else:
            loan.overdue_days = 0
            loan.estimated_fine = Decimal("0.00")

    # Reservations
    live_reservations = list(
        Reservation.objects.filter(
            student=student,
            status__in=[ReservationStatus.WAITING, ReservationStatus.NOTIFIED],
        )
        .select_related("book")
        .order_by("reserved_date")
    )

    ready_holds = [
        r
        for r in live_reservations
        if r.status == ReservationStatus.NOTIFIED and not r.has_expired
    ]
    waiting_holds = [
        r for r in live_reservations if r.status == ReservationStatus.WAITING
    ]

    # Fines
    unpaid_loans_with_fines = list(
        BorrowRecord.objects.filter(
            student=student,
            fine_paid=False,
            fine_amount__gt=Decimal("0.00"),
        )
        .select_related("book")
        .order_by("-returned_date")
    )
    total_unpaid_fines = sum(
        (f.fine_amount for f in unpaid_loans_with_fines), Decimal("0.00")
    )

    # All-time borrowing count
    total_borrowed_count = BorrowRecord.objects.filter(student=student).count()

    # Recent unread notifications
    recent_notifications = Notification.objects.filter(
        user=student,
        is_read=False,
    )[:5]

    return {
        "active_loans": active_loans,
        "active_loans_count": len(active_loans),
        "max_loans": rules.MAX_ACTIVE_LOANS,
        "loans_remaining_allowance": max(
            0, rules.MAX_ACTIVE_LOANS - len(active_loans)
        ),
        "ready_holds": ready_holds,
        "waiting_holds": waiting_holds,
        "total_reservations_count": len(live_reservations),
        "max_reservations": rules.MAX_ACTIVE_RESERVATIONS,
        "unpaid_fines": unpaid_loans_with_fines,
        "total_unpaid_fines": total_unpaid_fines,
        "total_borrowed_count": total_borrowed_count,
        "recent_notifications": recent_notifications,
    }


def get_librarian_dashboard_data():
    """
    Gather comprehensive institutional metrics for the librarian dashboard:
    - Catalogue totals (books, copies, shelf copies, active loans)
    - Critical circulation alerts (overdue loans, pending fines)
    - Member counts
    - Recent audit log entries
    - Top borrowed titles & category distribution
    """
    today = timezone.localdate()

    # Catalogue & copy metrics
    catalog_stats = Book.objects.filter(is_active=True).aggregate(
        total_titles=Count("id"),
        total_copies=Sum("quantity"),
        shelf_copies=Sum("available_quantity"),
    )
    total_titles = catalog_stats["total_titles"] or 0
    total_copies = catalog_stats["total_copies"] or 0
    shelf_copies = catalog_stats["shelf_copies"] or 0
    borrowed_copies = total_copies - shelf_copies

    # Active loans & overdue count
    active_loans_qs = BorrowRecord.objects.filter(
        returned_date__isnull=True
    ).select_related("student", "book")

    active_loans_count = active_loans_qs.count()
    overdue_loans = list(
        active_loans_qs.filter(due_date__lt=today).order_by("due_date")
    )
    for loan in overdue_loans:
        loan.overdue_days = rules.days_late(loan.due_date, today)
        loan.estimated_fine = rules.fine_for(loan.due_date, today)

    due_soon_count = active_loans_qs.filter(
        due_date__gte=today,
        due_date__lte=today + timedelta(days=rules.DUE_SOON_DAYS),
    ).count()

    # Student / member metrics
    total_students = User.objects.filter(role=User.Role.STUDENT).count()
    active_students_with_loans = (
        BorrowRecord.objects.filter(returned_date__isnull=True)
        .values("student")
        .distinct()
        .count()
    )

    # Fines metrics
    fines_agg = BorrowRecord.objects.filter(
        fine_paid=False,
        fine_amount__gt=Decimal("0.00"),
    ).aggregate(
        total_owing=Sum("fine_amount"),
        count_owing=Count("id"),
    )
    total_fines_owing = fines_agg["total_owing"] or Decimal("0.00")
    count_fines_owing = fines_agg["count_owing"] or 0

    # Live reservations waiting
    active_reservations_count = Reservation.objects.filter(
        status__in=[ReservationStatus.WAITING, ReservationStatus.NOTIFIED]
    ).count()

    # Recent audit trail
    recent_audit_logs = AuditLog.objects.select_related("user").order_by(
        "-timestamp"
    )[:10]

    # Popular books (top 5 most borrowed)
    popular_books = (
        Book.objects.annotate(
            borrow_times=Count("borrow_records"),
            avg_rating=Avg("reviews__rating"),
        )
        .filter(borrow_times__gt=0)
        .order_by("-borrow_times")[:5]
    )

    # Category distribution
    categories_with_counts = (
        Category.objects.annotate(
            book_count=Count("books", filter=Q(books__is_active=True))
        )
        .filter(book_count__gt=0)
        .order_by("-book_count")[:6]
    )

    return {
        "total_titles": total_titles,
        "total_copies": total_copies,
        "shelf_copies": shelf_copies,
        "borrowed_copies": borrowed_copies,
        "active_loans_count": active_loans_count,
        "overdue_loans": overdue_loans[:10],
        "overdue_loans_count": len(overdue_loans),
        "due_soon_count": due_soon_count,
        "total_students": total_students,
        "active_students_with_loans": active_students_with_loans,
        "total_fines_owing": total_fines_owing,
        "count_fines_owing": count_fines_owing,
        "active_reservations_count": active_reservations_count,
        "recent_audit_logs": recent_audit_logs,
        "popular_books": popular_books,
        "categories_with_counts": categories_with_counts,
    }
