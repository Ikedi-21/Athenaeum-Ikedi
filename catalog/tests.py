"""
Tests for the catalog app: models, ISBN validators, and catalog views.
"""

from datetime import date
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Book, Category, Review
from catalog.validators import validate_isbn


class ISBNValidatorTests(TestCase):
    def test_valid_isbn10(self):
        # 0471958697 is a valid ISBN-10
        validate_isbn("0-471-95869-7")
        validate_isbn("0471958697")

    def test_valid_isbn13(self):
        # 9780262033848 (Introduction to Algorithms)
        validate_isbn("978-0-262-03384-8")
        validate_isbn("9780262033848")

    def test_invalid_isbn_length(self):
        with self.assertRaises(ValidationError):
            validate_isbn("12345")

    def test_invalid_isbn_checksum(self):
        with self.assertRaises(ValidationError):
            validate_isbn("9780262033841")  # Invalid check digit


class CatalogModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Computer Science")
        self.book = Book.objects.create(
            title="Design Patterns",
            author="Gang of Four",
            isbn="9780201633610",
            category=self.category,
            quantity=3,
            available_quantity=3,
        )

    def test_category_slug_generated_on_save(self):
        self.assertEqual(self.category.slug, "computer-science")

    def test_book_availability_properties(self):
        self.assertTrue(self.book.is_available)
        self.assertEqual(self.book.borrowed_count, 0)

        self.book.available_quantity = 0
        self.book.save()
        self.assertFalse(self.book.is_available)
        self.assertEqual(self.book.borrowed_count, 3)

    def test_book_absolute_url(self):
        url = self.book.get_absolute_url()
        self.assertEqual(url, reverse("catalog:book_detail", kwargs={"pk": self.book.pk}))


class CatalogViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name="Fiction")
        self.book = Book.objects.create(
            title="Things Fall Apart",
            author="Chinua Achebe",
            isbn="9780385474542",
            category=self.category,
            quantity=2,
            available_quantity=2,
        )
        self.student = User.objects.create_user(
            username="student_reader",
            email="reader@athenaeum.edu",
            password="Password123!",
            role=User.Role.STUDENT,
        )

    def test_book_list_publicly_accessible(self):
        response = self.client.get(reverse("catalog:book_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Things Fall Apart")

    def test_book_search(self):
        response = self.client.get(reverse("catalog:book_list") + "?q=Achebe")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Things Fall Apart")

        response_empty = self.client.get(reverse("catalog:book_list") + "?q=NonExistentBook")
        self.assertEqual(response_empty.status_code, 200)
        self.assertNotContains(response_empty, "Things Fall Apart")

    def test_book_detail_view(self):
        response = self.client.get(self.book.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chinua Achebe")
        self.assertContains(response, "9780385474542")
