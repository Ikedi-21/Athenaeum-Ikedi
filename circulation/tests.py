"""
Tests for circulation business logic, borrowing, rules, and returns.
"""

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from catalog.models import Book, Category
from circulation import exceptions, rules, services
from circulation.models import BorrowRecord, Reservation, ReservationStatus

User = get_user_model()


class CirculationServicesTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="African Literature")
        self.student = User.objects.create_user(
            username="chinua_fan",
            email="chinua@athenaeum.edu",
            password="StrongPassword123!",
        )
        self.student2 = User.objects.create_user(
            username="wole_fan",
            email="wole@athenaeum.edu",
            password="StrongPassword123!",
        )
        self.book = Book.objects.create(
            title="Arrow of God",
            author="Chinua Achebe",
            isbn="9780385014809",
            category=self.category,
            quantity=1,
            available_quantity=1,
        )

    def test_borrow_and_return_cycle(self):
        # 1. Borrow book
        record = services.borrow_book(
            student=self.student,
            book=self.book,
        )
        self.book.refresh_from_db()
        self.assertEqual(self.book.available_quantity, 0)
        self.assertEqual(record.student, self.student)
        self.assertIsNone(record.returned_date)

        # 2. Cannot borrow again when already borrowed
        with self.assertRaises(exceptions.AlreadyBorrowed):
            services.borrow_book(
                student=self.student,
                book=self.book,
            )

        # 3. Another student cannot borrow because available_quantity is 0
        with self.assertRaises(exceptions.BookNotAvailable):
            services.borrow_book(
                student=self.student2,
                book=self.book,
            )

        # 4. Student 2 can reserve
        reservation = services.reserve_book(
            student=self.student2,
            book=self.book,
        )
        self.assertEqual(reservation.status, ReservationStatus.WAITING)

        # 5. Return book
        services.return_book(record=record, actor=self.student)
        self.book.refresh_from_db()
        record.refresh_from_db()
        self.assertIsNotNone(record.returned_date)

        # Returning offered copy to reservation
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.NOTIFIED)

    def test_max_loans_limit(self):
        # Create 3 distinct books and borrow them
        for i in range(rules.MAX_ACTIVE_LOANS):
            b = Book.objects.create(
                title=f"Book {i}",
                author="Author",
                isbn=f"97800000000{i}1",
                category=self.category,
                quantity=1,
                available_quantity=1,
            )
            services.borrow_book(student=self.student, book=b)

        # 4th borrow must fail
        b_extra = Book.objects.create(
            title="Extra Book",
            author="Author",
            isbn="9780000000099",
            category=self.category,
            quantity=1,
            available_quantity=1,
        )
        with self.assertRaises(exceptions.LoanLimitReached):
            services.borrow_book(student=self.student, book=b_extra)
