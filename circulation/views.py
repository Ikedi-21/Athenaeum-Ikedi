"""
Views for student circulation: active loans, loan history, and the five
circulation actions (borrow, reserve, renew, return, cancel reservation).
"""

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from catalog.models import Book

from . import rules, services
from .exceptions import CirculationError
from .models import (
    BorrowRecord,
    Reservation,
    ReservationStatus,
)


def money(amount):
    """Format a Decimal into standard currency presentation."""
    if amount is None:
        return "0.00"
    return f"{Decimal(amount):.2f}"


class CirculationActionView(LoginRequiredMixin, View):
    """
    Base view for POST-only circulation operations with safe next-redirect resolution
    and central CirculationError exception handling.
    """

    def get_success_url(self, default_url):
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()}
        ):
            return next_url
        return default_url


class LoanListView(LoginRequiredMixin, ListView):
    """
    List of active loans and live queue holds for the signed-in student.
    """

    template_name = "circulation/loan_list.html"
    context_object_name = "loans"

    def get_queryset(self):
        return (
            BorrowRecord.objects.filter(
                student=self.request.user,
                returned_date__isnull=True,
            )
            .select_related("book", "book__category")
            .order_by("due_date")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()

        # Holds waiting at desk (notified)
        holds = list(
            Reservation.objects.filter(
                student=user,
                status=ReservationStatus.NOTIFIED,
                expires_date__gt=timezone.now(),
            ).select_related("book")
        )

        # Queue reservations (waiting)
        waiting_reservations = list(
            Reservation.objects.filter(
                student=user,
                status=ReservationStatus.WAITING,
            ).select_related("book")
        )

        # Outstanding fines
        unpaid_fines = (
            BorrowRecord.objects.filter(
                student=user,
                fine_paid=False,
                fine_amount__gt=Decimal("0.00"),
            ).aggregate(total=Sum("fine_amount"))["total"]
            or Decimal("0.00")
        )

        context["holds"] = holds
        context["reservations"] = waiting_reservations
        context["reservation_count"] = len(holds) + len(waiting_reservations)
        context["loan_cap"] = rules.MAX_ACTIVE_LOANS
        context["reservation_cap"] = rules.MAX_ACTIVE_RESERVATIONS
        context["fine_total"] = unpaid_fines
        context["fine_per_day"] = rules.FINE_PER_DAY
        return context


class LoanHistoryView(LoginRequiredMixin, ListView):
    """
    Historical log of past returned loans and outstanding fine audit.
    """

    template_name = "circulation/loan_history.html"
    context_object_name = "loans"
    paginate_by = 10

    def get_queryset(self):
        return (
            BorrowRecord.objects.filter(
                student=self.request.user,
                returned_date__isnull=False,
            )
            .select_related("book")
            .order_by("-returned_date")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # All unpaid fines
        unpaid_loans = list(
            BorrowRecord.objects.filter(
                student=user,
                fine_paid=False,
                fine_amount__gt=Decimal("0.00"),
            ).select_related("book")
        )
        total_fines = sum((f.fine_amount for f in unpaid_loans), Decimal("0.00"))

        context["fines"] = unpaid_loans
        context["fine_total"] = total_fines
        context["fine_per_day"] = rules.FINE_PER_DAY
        return context


class BorrowView(CirculationActionView):
    """
    POST: Check out a book copy for the current student.
    """

    def post(self, request, pk):
        book = get_object_or_404(Book, pk=pk)
        try:
            record = services.borrow_book(
                student=request.user, book=book, request=request
            )
            messages.success(
                request,
                f"You have borrowed '{book.title}'. It is due back on {record.due_date:%d %B %Y}.",
            )
        except CirculationError as exc:
            messages.error(request, str(exc))

        return redirect(self.get_success_url(book.get_absolute_url()))


class ReserveView(CirculationActionView):
    """
    POST: Join the waiting queue for an unavailable book title.
    """

    def post(self, request, pk):
        book = get_object_or_404(Book, pk=pk)
        try:
            reservation = services.reserve_book(
                student=request.user, book=book, request=request
            )
            messages.success(
                request,
                f"You have reserved '{book.title}'. Your position in the queue is #{reservation.queue_position}.",
            )
        except CirculationError as exc:
            messages.error(request, str(exc))

        return redirect(self.get_success_url(book.get_absolute_url()))


class RenewView(CirculationActionView):
    """
    POST: Extend the due date of an active loan.
    """

    def post(self, request, pk):
        record = get_object_or_404(BorrowRecord, pk=pk)
        try:
            services.renew_loan(
                record=record, actor=request.user, request=request
            )
            messages.success(
                request,
                f"Loan for '{record.book.title}' has been renewed. New due date is {record.due_date:%d %B %Y}.",
            )
        except CirculationError as exc:
            messages.error(request, str(exc))

        return redirect(
            self.get_success_url(reverse("circulation:loans"))
        )


class ReturnView(CirculationActionView):
    """
    POST: Return a borrowed book copy to the shelf.
    """

    def post(self, request, pk):
        record = get_object_or_404(BorrowRecord, pk=pk)
        try:
            services.return_book(
                record=record, actor=request.user, request=request
            )
            if record.fine_amount > Decimal("0.00"):
                messages.warning(
                    request,
                    f"'{record.book.title}' returned late. Fine accrued: ₦{record.fine_amount:.2f}.",
                )
            else:
                messages.success(
                    request,
                    f"'{record.book.title}' has been returned successfully.",
                )
        except CirculationError as exc:
            messages.error(request, str(exc))

        return redirect(
            self.get_success_url(reverse("circulation:loans"))
        )


class CancelReservationView(CirculationActionView):
    """
    POST: Cancel a pending waiting list reservation.
    """

    def post(self, request, pk):
        reservation = get_object_or_404(Reservation, pk=pk)
        try:
            services.cancel_reservation(
                reservation=reservation, actor=request.user, request=request
            )
            messages.info(
                request,
                f"Your reservation for '{reservation.book.title}' has been cancelled.",
            )
        except CirculationError as exc:
            messages.error(request, str(exc))

        return redirect(
            self.get_success_url(reverse("circulation:loans"))
        )
