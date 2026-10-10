"""
Tests for catalog: models, constraints, and views.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Book, Category, Review

User = get_user_model()


class CatalogModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Computer Science")
        self.student = User.objects.create_user(
            username="student_reader",
            email="reader@athenaeum.edu",
            password="StrongPassword123!",
        )

    def test_category_slug_auto_generation(self):
        self.assertEqual(self.category.slug, "computer-science")

    def test_book_creation_and_properties(self):
        book = Book.objects.create(
            title="Clean Code",
            author="Robert C. Martin",
            isbn="9780132350884",
            category=self.category,
            quantity=3,
            available_quantity=3,
        )
        self.assertTrue(book.is_available)
        self.assertEqual(book.borrowed_count, 0)
        self.assertIn("openlibrary.org", book.open_library_url)

    def test_review_creation_and_rating_constraint(self):
        book = Book.objects.create(
            title="Design Patterns",
            author="Erich Gamma et al.",
            isbn="9780201633610",
            category=self.category,
            quantity=2,
            available_quantity=2,
        )
        review = Review.objects.create(
            book=book,
            student=self.student,
            rating=5,
            comment="Essential architectural guide.",
        )
        self.assertEqual(book.average_rating, 5.0)
        self.assertEqual(book.review_count, 1)

        # Duplicate review should violate unique constraint
        with self.assertRaises(IntegrityError):
            Review.objects.create(
                book=book,
                student=self.student,
                rating=4,
            )
