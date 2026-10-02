"""
Librarian views for managing library members (students).

Restricted to librarians through LibrarianRequiredMixin.
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.views.generic import DetailView, ListView

from accounts.mixins import LibrarianRequiredMixin
from accounts.models import User
from circulation.models import BorrowRecord, Reservation, ReservationStatus


class StudentListView(LibrarianRequiredMixin, ListView):
    """
    Searchable, filterable list of all registered student members.
    """

    model = User
    template_name = "accounts/student_list.html"
    context_object_name = "students"
    paginate_by = 15

    def get_queryset(self):
        qs = (
            User.objects.filter(role=User.Role.STUDENT)
            .annotate(
                active_loans_count=Count(
                    "borrow_records",
                    filter=Q(borrow_records__returned_date__isnull=True),
                ),
                total_borrowed_count=Count("borrow_records"),
                fines_owed=Sum(
                    "borrow_records__fine_amount",
                    filter=Q(
                        borrow_records__fine_paid=False,
                        borrow_records__fine_amount__gt=Decimal("0.00"),
                    ),
                ),
            )
            .order_by("username")
        )

        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )

        filter_status = self.request.GET.get("status", "all")
        if filter_status == "with_loans":
            qs = qs.filter(active_loans_count__gt=0)
        elif filter_status == "with_fines":
            qs = qs.filter(fines_owed__gt=Decimal("0.00"))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        context["status"] = self.request.GET.get("status", "all")
        context["total_student_count"] = User.objects.filter(
            role=User.Role.STUDENT
        ).count()
        return context


class StudentDetailView(LibrarianRequiredMixin, DetailView):
    """
    Detailed member profile view for librarians showing current loans,
    history, waitlist holds, and fine status.
    """

    model = User
    template_name = "accounts/student_detail.html"
    context_object_name = "student"

    def get_queryset(self):
        return User.objects.filter(role=User.Role.STUDENT)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = self.object

        active_loans = list(
            BorrowRecord.objects.filter(
                student=student,
                returned_date__isnull=True,
            )
            .select_related("book")
            .order_by("due_date")
        )

        borrowing_history = list(
            BorrowRecord.objects.filter(
                student=student,
                returned_date__isnull=False,
            )
            .select_related("book")
            .order_by("-returned_date")[:15]
        )

        active_reservations = list(
            Reservation.objects.filter(
                student=student,
                status__in=[
                    ReservationStatus.WAITING,
                    ReservationStatus.NOTIFIED,
                ],
            )
            .select_related("book")
            .order_by("reserved_date")
        )

        unpaid_fines = list(
            BorrowRecord.objects.filter(
                student=student,
                fine_paid=False,
                fine_amount__gt=Decimal("0.00"),
            ).select_related("book")
        )
        total_fines = sum(
            (f.fine_amount for f in unpaid_fines), Decimal("0.00")
        )

        context.update(
            {
                "active_loans": active_loans,
                "borrowing_history": borrowing_history,
                "active_reservations": active_reservations,
                "unpaid_fines": unpaid_fines,
                "total_fines": total_fines,
            }
        )
        return context
