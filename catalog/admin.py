"""
Admin registration for the catalogue.

The admin is a maintenance tool here, not the librarian's day to day
interface. Librarians add and edit books through the project's own pages,
which enforce the rules that matter, so what these classes are for is the
occasional job those pages deliberately do not offer: looking at a review
that has been reported, or removing a row that should never have existed.

Two columns are deliberately not editable from here even though the admin
could show them. available_quantity belongs to circulation and is moved by
borrowing and returning, and an existing slug is left alone because
rewriting one breaks every link already pointing at it. Both are explained
where they are set below.
"""

from django.contrib import admin
from django.db.models import Count

from .models import Book, Category, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Subject headings, with a count of what is filed under each."""

    list_display = ("name", "slug", "book_count")
    search_fields = ("name",)

    def get_queryset(self, request):
        """
        Count the books once for the whole page.

        Without this the count column would ask the database a separate
        question for every row on the page, which is the N plus 1 problem
        wearing an admin's clothes.
        """
        return super().get_queryset(request).annotate(
            book_count=Count("books")
        )

    @admin.display(description="Books", ordering="book_count")
    def book_count(self, category):
        """Read the annotation added above. ordering= makes the column
        sortable by delegating to the annotation rather than to Python."""
        return category.book_count

    def get_prepopulated_fields(self, request, obj=None):
        """
        Fill the slug in from the name while adding, and never afterwards.

        Django's prepopulation is JavaScript that rewrites the slug on every
        keystroke in the name field, which on a change form would quietly
        replace a working web address the moment somebody corrected a
        spelling. The field itself stays editable, so a slug can still be
        changed here on purpose. That is the difference this method is drawing:
        deliberately, yes, as a side effect of something else, no.
        """
        if obj is None:
            return {"slug": ("name",)}
        return {}


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """
    The catalogue itself.

    The list is built for the two questions actually asked of an admin: find
    one particular book, and see at a glance which books are withdrawn. Both
    counts are shown because the pair is what tells a story. Five owned and
    two on the shelf means three are out with students.
    """

    list_display = (
        "title",
        "author",
        "category",
        "isbn",
        "quantity",
        "available_quantity",
        "is_active",
    )

    # is_active first, because "show me the withdrawn ones" is the question
    # this page answers that the librarian pages answer less directly.
    list_filter = ("is_active", "category")

    # The same three fields the public search covers, so a librarian who has
    # learned one search box has learned both. ISBN is stored bare, without
    # hyphens, so a pasted 978-0-14-017739-8 will not match here. That is a
    # limitation of the admin's plain search and the reason the project has
    # its own search, which normalises the term before looking.
    search_fields = ("title", "author", "isbn")

    # One join instead of a query per row for the category column.
    list_select_related = ("category",)

    # Meta.ordering already sorts by title, and the admin appends the
    # primary key itself so that pagination cannot swap a row between pages,
    # which is why no ordering is set here.

    # A dropdown listing every category is fine with a dozen of them and
    # unusable with a thousand. Autocomplete searches instead, and works
    # because CategoryAdmin above defines search_fields.
    autocomplete_fields = ("category",)

    # Browse by acquisition date, which is how a maintainer finds "the batch
    # somebody imported last Tuesday".
    date_hierarchy = "added_date"

    # Three numbers that are shown and not typed. available_quantity is
    # moved by borrowing and returning, so a hand edit here would contradict
    # the loans on record: the librarian edit page is the supported way to
    # change how many copies exist, and it recalculates the shelf count
    # rather than trusting anybody's arithmetic. borrowed_count is derived
    # from the other two, and added_date is stamped once at creation.
    readonly_fields = ("available_quantity", "borrowed_count", "added_date")

    fieldsets = (
        (None, {"fields": ("title", "author", "isbn", "category")}),
        (
            "The book itself",
            {"fields": ("description", "published_date", "cover_image")},
        ),
        (
            "Copies",
            {"fields": ("quantity", "available_quantity", "borrowed_count")},
        ),
        ("In the collection", {"fields": ("is_active", "added_date")}),
    )

    # The same groups without the three derived rows, which on an add form
    # would show a shelf count and a loan count for a book that does not
    # exist yet. Named to match UserAdmin in accounts/admin.py, which draws
    # the same distinction for the same reason.
    add_fieldsets = (
        (None, {"fields": ("title", "author", "isbn", "category")}),
        (
            "The book itself",
            {"fields": ("description", "published_date", "cover_image")},
        ),
        ("Copies", {"fields": ("quantity",)}),
        ("In the collection", {"fields": ("is_active",)}),
    )

    def get_fieldsets(self, request, obj=None):
        """Use the shorter set while adding. obj is None only then."""
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj, form, change):
        """
        Put every copy of a brand new book on the shelf.

        available_quantity is not on the add form, so without this a book
        entered here would keep the field's default of one copy available
        however many copies were actually bought, and the rest would be
        invisible to students until somebody noticed. Nothing can be on loan
        before the book exists, so the total is the right shelf count.
        BookCreateView in manage_views.py does the same thing for the same
        reason, and this is the admin paying it the same respect.
        """
        if not change:
            obj.available_quantity = obj.quantity
        super().save_model(request, obj, form, change)

    @admin.display(description="On loan")
    def borrowed_count(self, book):
        """
        Show the model property under a label that reads as English.

        The property could be named in readonly_fields on its own, and Django
        would build a label from its name and call the row "Borrowed count".
        A method with @admin.display on it is how that becomes "On loan".
        Django resolves the name against the admin class before the model, so
        this method is what runs, and book.borrowed_count inside it is the
        property rather than a call back into here.
        """
        return book.borrowed_count

    # No bulk withdraw action, deliberately. Withdrawing a book also has to
    # release everybody queueing for it, which BookWithdrawView does inside
    # one transaction. An action here that only flipped is_active would
    # leave those students holding a place in a queue for a book the library
    # no longer lends, so withdrawing stays on the page that does it fully.


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """
    Student ratings and comments.

    This exists for moderation. A comment that should not be on a public
    page can be found here and removed, which is the one thing the project's
    own pages do not offer, since a student can edit their own review and
    nobody else's.
    """

    list_display = (
        "book",
        "student",
        "rating",
        "comment_preview",
        "created_date",
    )

    # Rating filters to the one star reviews, which is where a complaint
    # usually points. The date filter offers today and the last seven days.
    list_filter = ("rating", "created_date")

    # Searching the comment text is the point: a report names a phrase far
    # more often than it names a review.
    search_fields = ("book__title", "student__username", "comment")

    # Both columns follow a relation, so both are fetched in the one query.
    list_select_related = ("book", "student")

    # Dropdowns of every book and every user would be the two heaviest
    # selects in the project. Both target admins that define search_fields,
    # BookAdmin above and UserAdmin in accounts/admin.py.
    autocomplete_fields = ("book", "student")

    # Stamped at creation, so shown rather than offered.
    readonly_fields = ("created_date",)

    # Adding a duplicate review here is answered with a form error rather
    # than a crash, because the admin form displays both book and student
    # and so Django's own unique check covers the constraint across them.
    # ReviewForm has to check it by hand precisely because it hides those
    # two fields, which is what makes Django skip the check there.

    @admin.display(description="Comment")
    def comment_preview(self, review):
        """
        The opening of the comment, short enough to keep the row readable.

        Cut by hand rather than with Truncator, whose default marker is a
        single ellipsis character. Three full stops are used instead, in
        keeping with the rest of the project.
        """
        if not review.comment:
            return "Rating only"
        if len(review.comment) <= 60:
            return review.comment
        return review.comment[:60].rstrip() + "..."

