"""
Tests for dashboard views, notifications, and context processors.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import Notification

User = get_user_model()


class DashboardViewsTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username="test_student",
            email="test_student@athenaeum.edu",
            password="StrongPassword123!",
        )
        self.librarian = User.objects.create_superuser(
            username="test_librarian",
            email="test_librarian@athenaeum.edu",
            password="StrongPassword123!",
        )

    def test_student_dashboard_access(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/home.html")
        self.assertFalse(response.context["is_librarian_view"])

    def test_librarian_dashboard_access(self):
        self.client.force_login(self.librarian)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/home.html")
        self.assertTrue(response.context["is_librarian_view"])

    def test_notifications_workflow(self):
        self.client.force_login(self.student)
        notif = Notification.objects.create(
            user=self.student,
            kind=Notification.Kind.GENERAL,
            message="Welcome to Athenaeum Library!",
            link="/catalog/",
        )
        response = self.client.get(reverse("dashboard:notifications"))
        self.assertEqual(response.status_code, 200)

        # Mark read
        read_resp = self.client.get(
            reverse("dashboard:notification_read", kwargs={"pk": notif.pk})
        )
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
