"""
Tests for accounts app: authentication, registration, and student directory views.
"""

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User


class AccountsAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User.objects.create_user(
            username="student_user",
            email="student@athenaeum.edu",
            password="StrongPassword123!",
            role=User.Role.STUDENT,
        )
        self.librarian = User.objects.create_user(
            username="staff_user",
            email="staff@athenaeum.edu",
            password="StrongPassword123!",
            role=User.Role.LIBRARIAN,
        )

    def test_student_and_librarian_role_flags(self):
        self.assertTrue(self.student.is_student)
        self.assertFalse(self.student.is_librarian)

        self.assertTrue(self.librarian.is_librarian)
        self.assertFalse(self.librarian.is_student)

    def test_registration_view(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "new_student",
                "first_name": "New",
                "last_name": "Student",
                "email": "new.student@athenaeum.edu",
                "password1": "SafePassword123!",
                "password2": "SafePassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        new_user = User.objects.get(username="new_student")
        self.assertEqual(new_user.role, User.Role.STUDENT)
        self.assertTrue(new_user.is_student)

    def test_student_list_access_control(self):
        # Anonymous user redirected to login
        response_anon = self.client.get(reverse("accounts:student_list"))
        self.assertEqual(response_anon.status_code, 302)

        # Student user receives 403 Forbidden
        self.client.force_login(self.student)
        response_student = self.client.get(reverse("accounts:student_list"))
        self.assertEqual(response_student.status_code, 403)

        # Librarian user receives 200 OK
        self.client.force_login(self.librarian)
        response_librarian = self.client.get(reverse("accounts:student_list"))
        self.assertEqual(response_librarian.status_code, 200)
        self.assertContains(response_librarian, "student_user")


class AccountsSettingsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User.objects.create_user(
            username="student_reader",
            email="reader@athenaeum.edu",
            password="StrongPassword123!",
            role=User.Role.STUDENT,
        )
        self.librarian = User.objects.create_user(
            username="chief_librarian",
            email="chief@athenaeum.edu",
            password="StrongPassword123!",
            role=User.Role.LIBRARIAN,
        )

    def test_settings_requires_login(self):
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 302)

    def test_student_settings_access_and_admin_gate(self):
        self.client.force_login(self.student)
        # Student accesses profile tab
        response = self.client.get(f"{reverse('accounts:settings')}?tab=profile")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account Profile")
        self.assertNotContains(response, "Enterprise Admin Panel")

        # Student attempting to access admin config tab is redirected to profile
        response_admin_tab = self.client.get(f"{reverse('accounts:settings')}?tab=admin_config")
        self.assertEqual(response_admin_tab.status_code, 302)
        self.assertIn("tab=profile", response_admin_tab.url)

    def test_update_profile_action(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "action": "update_profile",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada.lovelace@athenaeum.edu",
                "phone_number": "+2348011223344",
                "bio": "Researching analytical computational machinery.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, "Ada")
        self.assertEqual(self.student.last_name, "Lovelace")
        self.assertEqual(self.student.email, "ada.lovelace@athenaeum.edu")
        self.assertEqual(self.student.user_settings.phone_number, "+2348011223344")
        self.assertEqual(self.student.user_settings.bio, "Researching analytical computational machinery.")

    def test_librarian_admin_settings_access(self):
        self.client.force_login(self.librarian)
        response = self.client.get(f"{reverse('accounts:settings')}?tab=admin_config")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enterprise System Configuration")
        self.assertContains(response, "Enterprise Admin Panel")

    def test_admin_system_config_update(self):
        self.client.force_login(self.librarian)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "action": "admin_update_system_config",
                "loan_duration_days": "21",
                "max_books_per_student": "5",
                "fine_rate_per_day": "75.00",
                "session_timeout_minutes": "90",
                "allow_student_reservations": "on",
                "webhook_url": "https://api.athenaeum.edu/webhooks/circulation",
            },
        )
        self.assertEqual(response.status_code, 302)

        from accounts.models import SystemConfig
        config = SystemConfig.get_solo()
        self.assertEqual(config.loan_duration_days, 21)
        self.assertEqual(config.max_books_per_student, 5)
        self.assertEqual(float(config.fine_rate_per_day), 75.00)
        self.assertEqual(config.session_timeout_minutes, 90)
        self.assertTrue(config.allow_student_reservations)

    def test_student_cannot_post_admin_action(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "action": "admin_update_system_config",
                "loan_duration_days": "100",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_legal_and_compliance_pages_accessible(self):
        # Unauthenticated users can view privacy, terms, and security overviews
        for url_name in ["accounts:privacy", "accounts:terms", "accounts:security"]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)

