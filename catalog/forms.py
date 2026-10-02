"""
Forms for the catalogue.

Three of them, and they divide along the same line the rest of the project
divides on: BookForm and CategoryForm are librarian tools, ReviewForm
belongs to students.

Two fields a librarian might expect to see on BookForm are deliberately
missing, and the reasoning is worth stating once here rather than in a
comment on each. available_quantity is circulation's column, moved by
borrowing and returning, and a librarian typing a figure into it directly
would silently contradict the loans on record. is_active is left out
because withdrawing a book from the collection is a decision with its own
page and its own confirmation, not a checkbox somebody can clear by
accident while fixing a spelling mistake.
"""

from django import forms
from django.utils.text import slugify

from .models import Book, Category, Review
from .validators import bare_isbn


class BookForm(forms.ModelForm):
    """
    Add a book to the catalogue, or correct one already in it.

    The same form serves both, which is what keeps a field from being
    editable on one page and not the other.
    """

    class Meta:
        model = Book
        # Listed explicitly rather than with exclude, so that adding a
        # field to the model later cannot quietly put it on this form. A
        # new column reaching a librarian's screen should be a decision,
        # not a side effect.
        fields = [
            "title",
            "author",
            "isbn",
            "category",
            "published_date",
            "description",
            "quantity",
            "cover_image",
            "digital_url",
            "digital_file",
        ]
        widgets = {
            # type="date" gives the browser's own date picker, and the
            # explicit format is what makes it prefill when editing. A
            # date input only recognises YYYY-MM-DD, so without this line
            # Django's localised rendering would hand it a value it cannot
            # read and the field would open blank on every edit.
            "published_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "description": forms.Textarea(attrs={"rows": 6}),
        }
        error_messages = {
            "isbn": {
                # Replaces Django's "Book with this ISBN already exists",
                # which is accurate but reads like a database talking. The
                # unique constraint on the column is what raises this, and
                # because clean_isbn below stores one canonical form, it
                # catches the same book entered twice even when the two
                # entries were typed with the hyphens in different places.
                "unique": (
                    "A book with that ISBN is already in the catalogue. "
                    "Search for it rather than adding it again, and change "
                    "the number of copies if the library has bought more."
                ),
            },
        }

    def __init__(self, *args, **kwargs):
        """
        Note how many copies are out on loan before anything is cleaned.

        This has to be read now, in __init__, and the timing is the whole
        point. self.instance still holds the values loaded from the
        database at this moment. Later, during validation, Django copies
        the submitted data onto that same instance, so by the time clean
        runs the old figures are gone and borrowed_count would be
        measuring the new quantity against the old shelf count.

        Zero for a book being added, which has no loans by definition.
        """
        super().__init__(*args, **kwargs)
        self.copies_on_loan = (
            self.instance.borrowed_count if self.instance.pk else 0
        )

    def clean_isbn(self):
        """
        Store one canonical spelling of the number.

        The same ISBN is printed with hyphens on one cover and without on
        the next, and a database comparing text sees two different values.
        Reducing it here means the unique constraint on the column is doing
        the job it looks like it is doing, and the search box can find the
        book whichever way a reader types it.

        The hyphens are not kept anywhere, which is a real if small loss:
        where the groups fall in an ISBN carries publisher information and
        it cannot be worked out again from the digits alone. A catalogue
        that has one entry per book is worth more than one that can print
        the number prettily.
        """
        # validate_isbn on the model field has already run by this point
        # and rejected anything that is not a real ISBN, so this is only
        # deciding how a number known to be valid should be written down.
        return bare_isbn(self.cleaned_data["isbn"])

    def clean_quantity(self):
        """
        Refuse a total lower than the number of copies already lent out.

        A library that owns three copies and has all three out cannot own
        one copy. Accepting it would leave the row describing something
        impossible, and the check constraint on the table would then have
        to be argued with instead of agreed with.

        Losses and damage are a separate matter. Reducing the total is for
        correcting a miscount, and a copy that has genuinely gone missing
        is still out on loan until somebody records it coming back.
        """
        quantity = self.cleaned_data["quantity"]
        if quantity < self.copies_on_loan:
            # Written to read correctly for one copy as well as several,
            # since "1 copies are out" is the sort of sentence that ends up
            # in a screenshot.
            subject = "copy is" if self.copies_on_loan == 1 else "copies are"
            raise forms.ValidationError(
                f"{self.copies_on_loan} {subject} out on loan, so the "
                f"library cannot be recorded as owning fewer than that. "
                f"Wait for them to come back first.",
                code="fewer_than_on_loan",
            )
        return quantity

    def clean_digital_file(self):
        """Ensure uploaded document is a valid e-book or PDF file."""
        uploaded = self.cleaned_data.get("digital_file")
        if uploaded and hasattr(uploaded, "name"):
            valid_extensions = (".pdf", ".epub", ".mobi")
            if not any(uploaded.name.lower().endswith(ext) for ext in valid_extensions):
                raise forms.ValidationError(
                    "Uploaded document must be a PDF or EPUB file (.pdf, .epub).",
                    code="invalid_ebook_format",
                )
        return uploaded


class CategoryForm(forms.ModelForm):
    """
    Add or rename a subject heading.

    The slug is not on the form. Category.save() generates it from the name
    the first time and then leaves it alone, on purpose: a slug that changes
    breaks every link and bookmark already pointing at the old one. So a
    librarian can correct a heading's spelling without silently breaking
    the address of the page it names.
    """

    class Meta:
        model = Category
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean_name(self):
        """
        Refuse a name that would generate a slug already in use.

        This is the gap left by keeping the slug off the form. Django's own
        unique checking skips any field the form does not show, so nothing
        else would notice that "Sci-Fi" and "Sci Fi" both reduce to sci-fi,
        and the clash would surface as a database error on save instead of
        a sentence next to the field.

        The name itself is unique too, but Django handles that one, because
        that field is on the form.
        """
        name = self.cleaned_data["name"]
        slug = slugify(name)

        # slugify strips everything that cannot appear in a URL, so a name
        # made only of punctuation reduces to an empty string. That would
        # save happily, since the field is blank=True, and then produce a
        # category whose address is /category// and matches no route at
        # all. Better refused here than discovered as a broken link.
        if not slug:
            raise forms.ValidationError(
                "That name has no letters or numbers in it, so no web "
                "address can be built from it. Include at least one.",
                code="slug_empty",
            )

        clash = Category.objects.filter(slug=slug)
        # An edit has to be allowed to keep its own slug, otherwise a
        # category could never be saved twice.
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        existing = clash.first()
        if existing is not None:
            raise forms.ValidationError(
                f"That name produces the same web address as the existing "
                f"category {existing.name}. Choose a name that differs by "
                f"more than punctuation.",
                code="slug_clash",
            )
        return name


# The wording next to each number, so a reader is not left guessing
# whether one star means best or worst. Kept at module level rather than
# inside the class so that anywhere else needing to offer the same five
# options, a rating filter for instance, imports this list instead of
# writing a second copy that will eventually disagree with this one.
RATING_CHOICES = [
    (1, "1 star, poor"),
    (2, "2 stars, fair"),
    (3, "3 stars, good"),
    (4, "4 stars, very good"),
    (5, "5 stars, excellent"),
]


class ReviewForm(forms.ModelForm):
    """
    A student's rating and comment on one book.

    Both fields the model needs and this form does not show, the book and
    the reviewer, are supplied by the view as keyword arguments rather than
    hidden inputs. A hidden field holding a user id is a field somebody can
    edit before submitting, and a review filed under another person's name
    is exactly the sort of thing that must not be possible.
    """

    # Overriding the model's own field rather than only its widget. The
    # model stores a small integer with validators allowing 1 to 5, which
    # Django would render as a number box: it accepts 7, then rejects it
    # after a round trip to the server. A dropdown offers the five real
    # answers and nothing else, so the invalid case cannot be typed.
    #
    # coerce=int is what turns the submitted "4" back into a number, since
    # every value arriving from a browser is a string and the model field
    # expects an integer. The blank first option means an unanswered form
    # fails with "this field is required" instead of quietly recording
    # whichever rating happened to sit at the top of the list.
    rating = forms.TypedChoiceField(
        choices=[("", "Choose a rating")] + RATING_CHOICES,
        coerce=int,
        label="Your rating",
    )

    class Meta:
        model = Review
        fields = ["rating", "comment"]
        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "What did you think of it?",
                }
            ),
        }
        labels = {"comment": "Your review"}
        help_texts = {
            # The model leaves comment blank=True, and saying so plainly
            # here is kinder than letting somebody wonder whether a rating
            # on its own will be accepted.
            "comment": "Optional. A rating on its own is fine.",
        }

    def __init__(self, *args, book=None, student=None, **kwargs):
        """
        Attach the book and the reviewer to the row being built.

        Setting them on self.instance here, rather than in the view after
        validation, is what lets clean() below see them and check for a
        review this student has already left. It also means the view's
        form.save() needs no follow up assignment.

        Both are keyword only and both default to None, because editing an
        existing review passes instance= instead and already has them.
        """
        super().__init__(*args, **kwargs)
        if book is not None:
            self.instance.book = book
        if student is not None:
            self.instance.student = student

    def clean(self):
        """
        Refuse a second review of the same book by the same student.

        The database already refuses it, through the
        one_review_per_student_per_book constraint, but a constraint
        breaking produces a server error page rather than a sentence on the
        form. The check has to happen here rather than being left to
        Django's own unique checking, which skips any constraint covering a
        field the form does not display, and this one covers two of them.

        A student who wants to change their mind edits the review they
        already left, which is why an instance with a primary key is exempt.
        """
        cleaned_data = super().clean()

        # The _id attributes rather than the objects themselves: reading
        # self.instance.book when nothing has been assigned raises
        # RelatedObjectDoesNotExist, while book_id is simply None. It also
        # saves a query, since the id is all the filter below needs.
        if self.instance.pk is None:
            book_id = self.instance.book_id
            student_id = self.instance.student_id
            already_reviewed = bool(book_id and student_id) and (
                Review.objects.filter(
                    book_id=book_id,
                    student_id=student_id,
                ).exists()
            )
            if already_reviewed:
                raise forms.ValidationError(
                    "You have already reviewed this book. Edit your "
                    "existing review to change what you said.",
                    code="duplicate_review",
                )

        return cleaned_data
