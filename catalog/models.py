"""
Catalogue models: the categories books are filed under, the books
themselves, and the reviews students leave on them.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from .validators import bare_isbn, validate_isbn


class Category(models.Model):
    """
    A subject heading a book is filed under, such as Fiction or Computer
    Science.

    This is a table rather than a set of choices on Book so that a
    librarian can add or rename a heading without a code change and a
    migration, and so that category pages can have their own URLs.
    """

    name = models.CharField(max_length=100, unique=True)

    # Used in the URL instead of the numeric id, so a category page reads
    # as /catalog/category/computer-science/ rather than ?category=3.
    # Left blank on the form because save() fills it in from the name.
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        help_text="Leave blank and it will be generated from the name.",
    )

    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        # Without this Django's admin would label the section "Categorys".
        verbose_name_plural = "categories"

    def __str__(self):
        """Shown in dropdowns, in the admin and anywhere a category prints."""
        return self.name

    def save(self, *args, **kwargs):
        """
        Generate the slug from the name the first time the row is saved.

        The check means an existing slug is never silently rewritten, which
        matters because a slug that changes breaks every link and bookmark
        already pointing at the old one.
        """
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """The canonical page for this category."""
        return reverse("catalog:category_detail", kwargs={"slug": self.slug})


class Book(models.Model):
    """
    A title the library holds, along with how many copies exist and how
    many of them are currently on the shelf.
    """

    # db_index helps the default ordering by title below. It does not
    # speed up the search box, because a LIKE pattern that starts with a
    # wildcard cannot use a B-tree index at all.
    title = models.CharField(max_length=200, db_index=True)

    author = models.CharField(max_length=200)

    isbn = models.CharField(
        "ISBN",
        max_length=17,
        unique=True,
        # 17 characters covers a 13 digit ISBN written with four hyphens.
        validators=[validate_isbn],
        help_text="10 or 13 digits. Hyphens are optional.",
    )

    # PROTECT means deleting a category that still has books raises an
    # error instead of quietly deleting the books with it. CASCADE here
    # would let one careless click empty a shelf.
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="books",
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

    digital_url = models.URLField(
        max_length=500,
        blank=True,
        help_text=(
            "Optional direct link to an online edition, Project Gutenberg, "
            "or an external repository."
        ),
    )

    digital_file = models.FileField(
        upload_to="book_digital/",
        blank=True,
        help_text="Optional open-access PDF or EPUB document for direct reading/download.",
    )

    # auto_now_add stamps this once at creation and never touches it
    # again, which is what the recently added section needs.
    added_date = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Uncheck to withdraw this book from the catalogue while keeping "
            "its borrowing history. Used instead of deleting a book that "
            "has ever been on loan."
        ),
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            # A database level guarantee that the shelf count can never
            # exceed the number of copies owned. PositiveIntegerField
            # already blocks negatives, so between the two it is
            # impossible for a bug in the borrow or return logic to leave
            # this book in an impossible state.
            models.CheckConstraint(
                condition=models.Q(available_quantity__lte=models.F("quantity")),
                name="available_not_greater_than_quantity",
            ),
        ]

    def __str__(self):
        """Shown in dropdowns, in the admin and in the audit log."""
        return f"{self.title} by {self.author}"

    def get_absolute_url(self):
        """The canonical page for this book."""
        return reverse("catalog:book_detail", kwargs={"pk": self.pk})

    @property
    def is_available(self):
        """
        True when a student could borrow this right now.

        A withdrawn book is never available even if copies are on the
        shelf, which is what keeps the two flags from contradicting each
        other in templates.
        """
        return self.is_active and self.available_quantity > 0

    @property
    def borrowed_count(self):
        """How many copies are currently out on loan."""
        return self.quantity - self.available_quantity

    @property
    def bare_isbn_clean(self):
        """The digits and check character of the ISBN without whitespace or hyphens."""
        return bare_isbn(self.isbn)

    @property
    def open_library_url(self):
        """Direct link to this book's page on Open Library."""
        return f"https://openlibrary.org/isbn/{self.bare_isbn_clean}"

    @property
    def internet_archive_url(self):
        """Search query link for this book on Internet Archive."""
        return f"https://archive.org/search?query=isbn%3A{self.bare_isbn_clean}"

    @property
    def effective_digital_url(self):
        """
        The primary digital destination:
        1. Custom uploaded file URL if present
        2. Custom external URL if provided
        3. Fallback to Open Library
        """
        if self.digital_file:
            return self.digital_file.url
        if self.digital_url:
            return self.digital_url
        return self.open_library_url

    @property
    def has_custom_digital(self):
        """True if the librarian has uploaded a file or specified a custom URL."""
        return bool(self.digital_file or self.digital_url)


class Review(models.Model):
    """
    A student's rating and optional written comment on a book.

    The average is deliberately not stored on Book. Views annotate it with
    Avg("reviews__rating") instead, so the figure is always derived from
    the rows that exist and cannot drift out of step with them.
    """

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    # Points at the setting rather than importing the User class, so the
    # user model can be swapped without editing every model that
    # references it.
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    # The validators give a friendly form error. The constraint below is
    # the real guarantee, since a validator only runs when something calls
    # full_clean() and a raw ORM create bypasses it entirely.
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5 stars.",
    )

    comment = models.TextField(blank=True)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest review first, which is what a book detail page wants.
        ordering = ["-created_date"]
        constraints = [
            # One review per student per book, so nobody can inflate a
            # rating by posting the same opinion ten times.
            models.UniqueConstraint(
                fields=["book", "student"],
                name="one_review_per_student_per_book",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        """Shown in the admin list and in the audit log."""
        return f"{self.student} rated {self.book.title} {self.rating}/5"
