"""
Catalogue views: browsing the shelves, searching them, and one book's page.

Every view in this module is public, and that is a decision rather than an
oversight. A library catalogue that will not tell you what it holds until
you have an account is not much of a catalogue, so browsing, searching and
reading reviews are open to anybody. The login requirement starts at
borrowing.

The searching, filtering and sorting live in a mixin rather than on the
list view itself. The librarian's management list, in manage_views.py,
needs all three and needs withdrawn books as well, and if it reached them
by subclassing the public view it would inherit login_not_required along
with them. Sharing through a mixin means neither list can quietly acquire
the other's permissions.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, ListView
from django.views.generic.edit import FormMixin

from .forms import ReviewForm
from .models import Book, Category, Review
from .validators import bare_isbn


# The sort dropdown, written as data rather than as a chain of if
# statements. The key is what travels in the query string, the label is
# what the reader sees, and the ordering is what reaches the database.
#
# That last part is the reason this is a lookup table and not a shortcut.
# order_by is happy to follow a relation, so a view that passed ?sort=
# straight through would let a visitor order the shelf by
# reviews__student__password and read information out of the row order. A
# value that is not a key here never reaches the database at all.
SORT_OPTIONS = {
    "newest": {
        "label": "Recently added",
        # pk settles any remaining tie. Without a fully determined order a
        # book sharing a value with another can swap sides between page one
        # and page two, which loses it from a list it never left.
        "ordering": ("-added_date", "pk"),
    },
    "title": {
        "label": "Title A to Z",
        "ordering": ("title", "pk"),
    },
    "author": {
        "label": "Author A to Z",
        "ordering": ("author", "title", "pk"),
    },
    "rating": {
        "label": "Highest rated",
        # nulls_last is stated rather than assumed. Databases disagree
        # about where NULL belongs in an ordering, and a book nobody has
        # reviewed has no average at all, so without this a book with no
        # reviews could head a list of the best reviewed ones.
        "ordering": (
            F("average_rating").desc(nulls_last=True),
            "title",
            "pk",
        ),
    },
    "popular": {
        "label": "Most borrowed",
        "ordering": ("-times_borrowed", "title", "pk"),
        # Counting loans means a second join, so it is annotated only when
        # this ordering is the one asked for. See BookQueryMixin.
        "needs_loan_count": True,
    },
}


# Used when the query string says nothing, and when it says something this
# module does not recognise.
DEFAULT_SORT = "newest"


class BookQueryMixin:
    """
    The search box, the category dropdown and the sort dropdown.

    Three query string parameters are read: q for the search, category for
    the dropdown and sort for the ordering. All three are optional, and all
    three survive a page change because the pagination links are built with
    Django's querystring tag, which rewrites only the page number and
    leaves everything else alone.
    """

    context_object_name = "books"

    # Twelve divides evenly into two, three and four columns, so the last
    # row of the grid is never left ragged at any screen width.
    paginate_by = 12

    def base_queryset(self):
        """
        Every book this particular list is allowed to show.

        The single override point of this mixin. The public list hides
        withdrawn books, the librarian's management list has to include
        them so they can be restored, and nothing else about searching or
        sorting differs between the two.

        Withdrawn rather than deleted, because a book with loan history
        cannot leave the database without taking that history with it, so
        is_active False is what "removed" means to a reader.
        """
        return Book.objects.filter(is_active=True)

    def get_search_term(self):
        """Whatever was typed into the search box, or an empty string."""
        return self.request.GET.get("q", "").strip()

    def lookup_selected_category(self):
        """
        The category chosen in the dropdown, or None if none was.

        An unrecognised slug is ignored here rather than raising a 404,
        which is the opposite of what the category page does further down.
        The difference is deliberate. A slug in the path is an address, and
        a wrong one is a broken link worth reporting. A slug in a query
        string is a filter, and a stale bookmark naming a category that has
        since been renamed is better answered with the whole shelf than
        with an error page.
        """
        slug = self.request.GET.get("category", "").strip()
        if not slug:
            return None
        return Category.objects.filter(slug=slug).first()

    def get_selected_category(self):
        """
        The chosen category, looked up once per request.

        get_queryset and get_context_data both need it, and the cache is
        what stops the second one repeating the first one's query. hasattr
        rather than "or None", because None is a real answer here and would
        otherwise be looked up again every time.
        """
        if not hasattr(self, "_selected_category"):
            self._selected_category = self.lookup_selected_category()
        return self._selected_category

    def get_sort_key(self):
        """
        The chosen ordering, checked against SORT_OPTIONS.

        Anything unrecognised quietly becomes the default rather than an
        error, since a sort order is a preference and not the address of
        anything.
        """
        key = self.request.GET.get("sort", DEFAULT_SORT)
        return key if key in SORT_OPTIONS else DEFAULT_SORT

    def search_filter(self, term):
        """
        Build the Q object describing where the search box looks.

        Title, author and ISBN. A substring match, so gatsby finds The
        Great Gatsby. The cost of keeping it that simple is that word order
        matters, since the words are not split apart, so "gatsby great"
        finds nothing. Worth stating plainly rather than implying more.

        icontains is case insensitive whichever way the words were typed.
        """
        matches = Q(title__icontains=term) | Q(author__icontains=term)

        # An ISBN is stored with its hyphens removed, so the term has to be
        # reduced the same way before it can match: 978-0-14 would
        # otherwise never find 9780141036144. The test that follows keeps
        # ordinary words out of the ISBN clause, because collapsing "the
        # great" into THEGREAT and asking a database whether any ISBN
        # contains it is a question with only one possible answer.
        digits = bare_isbn(term)
        if digits and all(char in "0123456789X" for char in digits):
            matches |= Q(isbn__icontains=digits)

        return matches

    def get_queryset(self):
        """
        Search, then filter, then order, on top of whatever this list may
        show.

        select_related pulls each book's category into the same query,
        because the cards print the category name inside a loop and every
        one of them would otherwise cost an extra query. That is the N plus
        1 problem, and it is the reason this is not left to the default.

        average_rating and review_count are annotated on every request
        because the cards display them. times_borrowed is annotated only
        for the popularity sort, since it adds a second multi valued join
        for a number nothing else shows.

        Two such joins together need care. Each loan row repeats every
        review row, so both counts ask for distinct=True and count rows
        once each. Avg needs no such treatment: repeating every rating the
        same number of times leaves the average exactly where it was.
        """
        option = SORT_OPTIONS[self.get_sort_key()]

        queryset = (
            self.base_queryset()
            .select_related("category")
            .annotate(
                average_rating=Avg("reviews__rating"),
                review_count=Count("reviews", distinct=True),
            )
        )

        if option.get("needs_loan_count"):
            queryset = queryset.annotate(
                times_borrowed=Count("borrow_records", distinct=True)
            )

        term = self.get_search_term()
        if term:
            queryset = queryset.filter(self.search_filter(term))

        category = self.get_selected_category()
        if category is not None:
            queryset = queryset.filter(category=category)

        # Stated last so that an ordering naming an annotation is applied
        # after the annotation exists.
        return queryset.order_by(*option["ordering"])

    def get_category_choices(self):
        """
        The categories for the dropdown, each with a count beside it.

        filter= inside Count is what keeps withdrawn books out of that
        number, so the figure next to a heading agrees with how many cards
        a reader finds after choosing it. Conditional counting like this is
        one query for the whole dropdown, where a count per category would
        be one query each.

        Empty categories are left in. A heading reading Poetry 0 tells a
        reader something true, and hiding it would hide a librarian's newly
        added heading from the librarian who just added it.
        """
        return Category.objects.annotate(
            book_count=Count("books", filter=Q(books__is_active=True))
        )

    def get_context_data(self, **kwargs):
        """
        Hand the controls above the grid everything they need to redraw
        themselves in the state the reader left them in.

        A filter form that forgets what was typed into it is the commonest
        way for a list like this to feel broken, so the search term, the
        chosen category and the chosen sort all go back to the template.

        selected_category is the slug rather than the object, because all
        the template does with it is decide which option carries the
        selected attribute, and comparing two strings there is clearer than
        reaching through a relation.
        """
        context = super().get_context_data(**kwargs)
        selected = self.get_selected_category()

        context["search_term"] = self.get_search_term()
        context["selected_category"] = selected.slug if selected else ""
        context["selected_sort"] = self.get_sort_key()
        context["sort_options"] = [
            (key, option["label"]) for key, option in SORT_OPTIONS.items()
        ]
        context["categories"] = self.get_category_choices()
        return context


@method_decorator(login_not_required, name="dispatch")
class BookListView(BookQueryMixin, ListView):
    """
    The browsable shelf: every book the library lends, searchable.

    All of the behaviour is in BookQueryMixin. What this class adds is the
    template, and the decision that the public sees only books still in the
    lending collection, which is base_queryset's default and so is not
    repeated here.
    """

    model = Book
    template_name = "catalog/book_list.html"


@method_decorator(login_not_required, name="dispatch")
class CategoryBookListView(BookListView):
    """
    The same shelf, narrowed to one category by its own URL.

    Subclassing the public list keeps the page size, the template and the
    search and sort behaviour identical, so a category page cannot drift
    out of step with the main one. Searching and sorting keep working
    inside it.
    """

    def lookup_selected_category(self):
        """
        The category named in the path, which overrides the dropdown.

        get_object_or_404 rather than a filter that quietly returns
        nothing, so a mistyped or renamed slug is reported as a missing page
        instead of an empty shelf, which would look like a real answer to a
        question nobody asked.

        Overriding the lookup rather than get_selected_category leaves the
        caching in the mixin, where one copy of it serves both classes.
        """
        return get_object_or_404(Category, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        """Name the category, so the heading can say what is being shown."""
        context = super().get_context_data(**kwargs)
        context["category"] = self.get_selected_category()
        return context


@method_decorator(login_not_required, name="dispatch")
class BookDetailView(FormMixin, DetailView):
    """
    One book, its details, its reviews, and the form to leave one.

    Reading the page is public. Writing a review is not, and because the
    class is marked login_not_required the middleware will not stop the
    POST, so this view checks for itself. Both halves of that live in post
    below, which is the only method here that changes anything.

    Reviewing is open to any signed in student rather than only to students
    who have borrowed the book. The rule against rating a book twice is
    already enforced by a constraint, and requiring a loan first would
    leave every book in a new library showing an empty review section with
    no way to start one.
    """

    model = Book
    template_name = "catalog/book_detail.html"
    context_object_name = "book"
    form_class = ReviewForm

    def get_queryset(self):
        """
        A withdrawn book gives a 404 rather than a page.

        prefetch_related is used for the reviews rather than select_related
        because a book has many of them, and select_related can only follow
        a relation leading to a single row. Naming reviews__student in the
        same call fetches the reviewers too, so printing a name under each
        review costs no further queries.

        The two annotations are the same pair the shelf cards use, so the
        average shown on a card and the average shown on the page it links
        to are calculated the same way and cannot disagree.
        """
        return (
            Book.objects.filter(is_active=True)
            .select_related("category")
            .annotate(
                average_rating=Avg("reviews__rating"),
                review_count=Count("reviews", distinct=True),
            )
            .prefetch_related("reviews__student")
        )

    def get_success_url(self):
        """Back to the book, where the new review is now visible."""
        return self.object.get_absolute_url()

    def may_review(self):
        """
        Whether the person reading this page is allowed to review the book.

        Students only. is_authenticated is tested first because
        AnonymousUser has no is_student attribute at all, and the order of
        an and is what keeps that from being an error rather than a no.
        """
        user = self.request.user
        return user.is_authenticated and user.is_student

    def get_existing_review(self):
        """
        This student's own review of this book, or None.

        Looked up so the form can be handed it as an instance, which turns
        a second attempt at reviewing into an edit of the first rather than
        an error. Cached because get_form_kwargs and get_context_data both
        want it.
        """
        if not hasattr(self, "_existing_review"):
            self._existing_review = (
                Review.objects.filter(
                    book=self.object, student=self.request.user
                ).first()
                if self.may_review()
                else None
            )
        return self._existing_review

    def get_form_kwargs(self):
        """
        Give the form either the review being edited or the pair of rows a
        new one needs.

        The book and the student are passed as arguments rather than
        rendered as hidden inputs, because a hidden field holding a user id
        is a field somebody can change before submitting, and a review
        filed under another person's name must not be possible.
        """
        kwargs = super().get_form_kwargs()
        existing = self.get_existing_review()
        if existing is not None:
            kwargs["instance"] = existing
        else:
            kwargs["book"] = self.object
            kwargs["student"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        """
        Add the review form, but only for somebody who can use it.

        FormMixin would otherwise build one for every visitor, including
        anonymous ones, and the template would show a signed out reader a
        form that cannot work. Setting form to None instead lets the
        template ask a plain question: if there is a form, draw it.

        setdefault rather than assignment, because form_invalid passes the
        bound form with its error messages through this same method and
        overwriting it there would throw those messages away.
        """
        if self.may_review():
            kwargs.setdefault("form", self.get_form())
            kwargs.setdefault("existing_review", self.get_existing_review())
        else:
            kwargs.setdefault("form", None)
        return super().get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        """
        Receive a review, having first established who is sending it.

        self.object is set by hand because DetailView only does that during
        a GET, and everything below, the permission checks included, needs
        to know which book is being reviewed.

        A signed out visitor is sent to log in and returned here afterwards
        rather than shown an error, since a session that quietly expired
        while the page was open is the likeliest way to arrive here. A
        librarian is refused outright: reviewing is a reader's act, and a
        librarian rating the library's own stock is not what the section is
        for.
        """
        self.object = self.get_object()

        if not request.user.is_authenticated:
            # get_full_path keeps any query string, so the reader lands back
            # on the same page rather than at the top of the catalogue.
            return redirect_to_login(request.get_full_path())

        if not request.user.is_student:
            raise PermissionDenied(
                "Only student accounts can review books."
            )

        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        """
        Save the review and say so, then redirect.

        Whether this was a first review or a correction has to be read
        before the save, because saving is what gives a new row its primary
        key and the question becomes unanswerable a line later.

        The redirect afterwards is deliberate rather than incidental. It
        means a refresh reloads a page instead of resubmitting the form,
        which is what would otherwise turn one accidental keypress into a
        second attempt at a review that already exists.
        """
        was_edit = form.instance.pk is not None
        form.save()

        messages.success(
            self.request,
            "Your review has been updated."
            if was_edit
            else "Thank you. Your review has been added.",
        )
        return super().form_valid(form)
