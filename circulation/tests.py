"""
Tests for circulation business logic, services, and student/librarian desk operations.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Book, Category
from circulation import exceptions, rules, services
from circulation.models import BorrowRecord, Reservation, ReservationStatus


class CirculationBusinessLogicTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Science")
        self.book1 = Book.objects.create(
            title="Quantum Mechanics",
            author="David J. Griffiths",
            isbn="9780131118928",
            category=self.category,
            quantity=2,
            available_quantity=2,
        )
        self.book2 = Book.objects.create(
            title="Electrodynamics",
            author="David J. Griffiths",
            isbn="9780138053260",
            category=self.category,
            quantity=1,
            available_quantity=1,
        )
        self.book3 = Book.objects.create(
            title="Thermal Physics",
            author="Daniel V. Schroeder",
            isbn="9780201380279",
            category=self.category,
            quantity=1,
            available_quantity=1,
        )
        self.book4 = Book.objects.create(
            title="Classical Mechanics",
            author="John R. Taylor",
            isbn="9781891389221",
            category=self.category,
            quantity=1,
            available_quantity=1,
        )

        self.student = User.objects.create_user(
            username="ada_lovelace",
            email="ada@athenaeum.edu",
            password="Password123!",
            role=User.Role.STUDENT,
        )
        self.librarian = User.objects.create_user(
            username="head_librarian",
            email="librarian@athenaeum.edu",
            password="Password123!",
            role=User.Role.LIBRARIAN,
        )

    def test_borrow_available_book_decreases_quantity(self):
        record = services.borrow_book(student=self.student, book=self.book1)
        self.book1.refresh_from_db()
        self.assertEqual(self.book1.available_quantity, 1)
        self.assertFalse(record.is_returned)
        self.assertEqual(record.student, self.student)

    def test_cannot_borrow_same_book_twice_concurrently(self):
        services.borrow_book(student=self.student, book=self.book1)
        with self.assertRaises(exceptions.AlreadyBorrowed):
            services.borrow_book(student=self.student, book=self.book1)

    def test_cannot_exceed_maximum_active_loans(self):
        services.borrow_book(student=self.student, book=self.book1)
        services.borrow_book(student=self.student, book=self.book2)
        services.borrow_book(student=self.student, book=self.book3)

        self.assertEqual(services.active_loans(self.student).count(), 3)

        # Attempting 4th loan must raise LoanLimitReached
        with self.assertRaises(exceptions.LoanLimitReached):
            services.borrow_book(student=self.student, book=self.book4)

    def test_return_book_increases_available_quantity(self):
        record = services.borrow_book(student=self.student, book=self.book1)
        self.book1.refresh_from_db()
        self.assertEqual(self.book1.available_quantity, 1)

        services.return_book(record=record, actor=self.student)
        self.book1.refresh_from_db()
        self.assertEqual(self.book1.available_quantity, 2)
        record.refresh_from_db()
        self.assertTrue(record.is_returned)
        self.assertEqual(record.fine_amount, Decimal("0.00"))

    def test_late_return_incurs_fine(self):
        record = services.borrow_book(student=self.student, book=self.book1)
        # Set due date 4 days in past
        today = timezone.localdate()
        BorrowRecord.objects.filter(pk=record.pk).update(
            due_date=today - timedelta(days=4)
        )
        record.refresh_from_db()

        returned_record = services.return_book(record=record, actor=self.student)
        expected_fine = Decimal("4") * rules.FINE_PER_DAY
        self.assertEqual(returned_record.fine_amount, expected_fine)
        self.assertFalse(returned_record.fine_paid)

    def test_renew_loan_extends_due_date(self):
        record = services.borrow_book(student=self.student, book=self.book1)
        initial_due = record.due_date

        renewed = services.renew_loan(record=record, actor=self.student)
        self.assertEqual(renewed.renewal_count, 1)
        self.assertEqual(renewed.due_date, initial_due + timedelta(days=rules.RENEWAL_PERIOD_DAYS))

    def test_reserve_book_when_unavailable(self):
        # Empty out shelf copies
        self.book2.available_quantity = 0
        self.book2.save()

        reservation = services.reserve_book(student=self.student, book=self.book2)
        self.assertEqual(reservation.status, ReservationStatus.WAITING)
        self.assertEqual(reservation.queue_position(), 1)

    def test_cannot_reserve_book_when_copy_available(self):
        # Book 1 has available copies
        with self.assertRaises(exceptions.CopiesAvailable):
            services.reserve_book(student=self.student, book=self.book1)
