"""
Tests for dashboard views, analytics helpers, and notifications.
"""

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Book, Category
from circulation.models import BorrowRecord
from dashboard.models import Notification


class DashboardViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name="Philosophy")
        self.book = Book.objects.create(
            title="Nicomachean Ethics",
            author="Aristotle",
            isbn="9780199213610",
            category=self.category,
            quantity=2,
            available_quantity=2,
        )

        self.student = User.objects.create_user(
            username="student_tester",
            email="tester@athenaeum.edu",
            password="Password123!",
            role=User.Role.STUDENT,
        )
        self.librarian = User.objects.create_user(
            username="librarian_tester",
            email="staff_test@athenaeum.edu",
            password="Password123!",
            role=User.Role.LIBRARIAN,
        )

    def test_student_dashboard_view(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome, student_tester")
        self.assertContains(response, "Active Books on Loan")

    def test_librarian_dashboard_view(self):
        self.client.force_login(self.librarian)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Library Administration")
        self.assertContains(response, "Catalogue Titles")
        self.assertContains(response, "Loan Desk")

    def test_notifications_flow(self):
        # Create notification for student
        notification = Notification.objects.create(
            user=self.student,
            kind=Notification.Kind.RESERVATION_READY,
            message="Your copy of Nicomachean Ethics is ready for pickup!",
            link="/loans/",
        )
        self.assertFalse(notification.is_read)

        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nicomachean Ethics")

        # Mark read
        post_response = self.client.post(
            reverse("dashboard:notification_read", kwargs={"pk": notification.pk})
        )
        self.assertEqual(post_response.status_code, 302)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
