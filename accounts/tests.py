"""
Tests for accounts: models, roles, and registration.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_student_user(self):
        user = User.objects.create_user(
            username="student1",
            email="student1@athenaeum.edu",
            password="StrongPassword123!",
        )
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertTrue(user.is_student)
        self.assertFalse(user.is_librarian)

    def test_create_librarian_superuser(self):
        admin_user = User.objects.create_superuser(
            username="librarian1",
            email="librarian1@athenaeum.edu",
            password="StrongPassword123!",
        )
        self.assertEqual(admin_user.role, User.Role.LIBRARIAN)
        self.assertTrue(admin_user.is_librarian)
        self.assertFalse(admin_user.is_student)

    def test_user_settings_auto_creation(self):
        user = User.objects.create_user(
            username="student2",
            email="student2@athenaeum.edu",
            password="StrongPassword123!",
        )
        settings_obj = user.user_settings
        self.assertIsNotNone(settings_obj)
        self.assertEqual(settings_obj.theme, "light")


class RegistrationViewTests(TestCase):
    def test_student_registration(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newstudent",
                "first_name": "New",
                "last_name": "Student",
                "email": "newstudent@athenaeum.edu",
                "password": "ValidPassword123!",
                "password2": "ValidPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.filter(username="newstudent").first()
        self.assertIsNotNone(created)
        self.assertTrue(created.is_student)
