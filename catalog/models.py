"""
Models for the library catalogue: categories, books, and student reviews.
"""

from urllib.parse import quote_plus
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, CheckConstraint, F, Q, UniqueConstraint
from django.urls import reverse
from django.utils.text import slugify

from .validators import bare_isbn, validate_isbn


class Category(models.Model):
    """
    Subject heading for books in the catalogue.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        help_text="Leave blank and it will be generated from the name.",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:category_detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Book(models.Model):
    """
    A bibliographic book title in the library holding.
    """

    title = models.CharField(max_length=200, db_index=True)
    author = models.CharField(max_length=200)
    isbn = models.CharField(
        max_length=17,
        unique=True,
        validators=[validate_isbn],
        verbose_name="ISBN",
        help_text="10 or 13 digits. Hyphens are optional.",
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="books"
    )
    published_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="Total copies the library owns.",
    )
    available_quantity = models.PositiveIntegerField(
        default=1,
        help_text="Copies on the shelf right now, not out on loan.",
    )
    cover_image = models.ImageField(
        upload_to="book_covers/",
        blank=True,
        help_text="Optional. A placeholder is shown when this is empty.",
    )
    digital_file = models.FileField(
        upload_to="book_digital/",
        blank=True,
        help_text="Optional open-access PDF or EPUB document for direct reading/download.",
    )
    digital_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Optional direct link to an online edition, Project Gutenberg, or an external repository.",
    )
    added_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Uncheck to withdraw this book from the catalogue while keeping "
            "its borrowing history. Used instead of deleting a book that has "
            "ever been on loan."
        ),
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            CheckConstraint(
                condition=Q(available_quantity__lte=F("quantity")),
                name="available_not_greater_than_quantity",
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    def get_absolute_url(self):
        return reverse("catalog:book_detail", kwargs={"pk": self.pk})

    @property
    def borrowed_count(self):
        """Copies currently held by borrowers."""
        return max(0, self.quantity - self.available_quantity)

    @property
    def is_available(self):
        """True when there is at least one copy on shelf and book is active."""
        return self.is_active and self.available_quantity > 0

    @property
    def average_rating(self):
        """Compute live average review rating."""
        res = self.reviews.aggregate(avg=Avg("rating"))["avg"]
        return res

    @property
    def review_count(self):
        """Total submitted reviews."""
        return self.reviews.count()

    @property
    def has_digital_edition(self):
        """True if an uploaded file or external direct digital link is configured."""
        return bool(self.digital_file or self.digital_url)

    @property
    def clean_isbn(self):
        """ISBN stripped of hyphens and whitespace."""
        return bare_isbn(self.isbn)

    @property
    def open_library_url(self):
        """Deep link to Open Library repository by ISBN."""
        return f"https://openlibrary.org/isbn/{self.clean_isbn}"

    @property
    def internet_archive_url(self):
        """Deep search URL on Internet Archive."""
        query = quote_plus(f"{self.title} {self.author}")
        return f"https://archive.org/search.php?query={query}"

    @property
    def effective_digital_url(self):
        """
        Preferred direct digital reading link:
        Uploaded document file > Direct configured URL > Open Library link.
        """
        if self.digital_file:
            return self.digital_file.url
        if self.digital_url:
            return self.digital_url
        return self.open_library_url


class Review(models.Model):
    """
    A student review and star rating for a book.
    """

    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name="reviews"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5 stars.",
    )
    comment = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]
        constraints = [
            UniqueConstraint(
                fields=["book", "student"],
                name="one_review_per_student_per_book",
            ),
            CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.student} on {self.book} ({self.rating}/5)"
