"""
Public views for the library catalogue: shelf lists, search, category browsing,
and book detail with review management and digital edition reading.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, ListView

from circulation.models import BorrowRecord

from .forms import ReviewForm
from .models import Book, Category, Review

SORT_OPTIONS = {
    "title": {"label": "Title, A to Z", "order_by": ["title"]},
    "author": {"label": "Author, A to Z", "order_by": ["author", "title"]},
    "newest": {"label": "Newest additions", "order_by": ["-added_date", "title"]},
    "rating": {"label": "Highest rated", "order_by": ["-avg_rating", "title"]},
    "popular": {"label": "Most popular", "order_by": ["-borrow_count", "title"]},
}

DEFAULT_SORT = "title"


class BookQueryMixin:
    """
    Search, category filtering, rating annotations, and sorting for book listings.
    Shared across public shelf view and librarian catalogue management list.
    """

    paginate_by = 12
    context_object_name = "books"

    def base_queryset(self):
        return Book.objects.filter(is_active=True)

    def get_search_term(self):
        return self.request.GET.get("q", "").strip()

    def get_selected_category(self):
        return self.request.GET.get("category", "").strip()

    def get_selected_sort(self):
        sort = self.request.GET.get("sort", DEFAULT_SORT)
        return sort if sort in SORT_OPTIONS else DEFAULT_SORT

    def get_category_choices(self):
        return Category.objects.annotate(
            book_count=Count("books", filter=Q(books__is_active=True))
        )

    def get_queryset(self):
        qs = (
            self.base_queryset()
            .select_related("category")
            .annotate(
                avg_rating=Avg("reviews__rating"),
                review_count=Count("reviews", distinct=True),
                borrow_count=Count("borrow_records", distinct=True),
            )
        )

        # 1. Search Query
        q = self.get_search_term()
        if q:
            clean_q = q.replace("-", "").replace(" ", "")
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(author__icontains=q)
                | Q(isbn__icontains=clean_q)
                | Q(isbn__icontains=q)
            )

        # 2. Category Filter
        cat_slug = self.get_selected_category()
        if cat_slug:
            qs = qs.filter(category__slug=cat_slug)

        # 3. Sorting
        sort_key = self.get_selected_sort()
        order_fields = SORT_OPTIONS[sort_key]["order_by"]
        return qs.order_by(*order_fields)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.get_search_term()
        context["selected_category"] = self.get_selected_category()
        context["selected_sort"] = self.get_selected_sort()
        context["sort_options"] = [
            (k, v["label"]) for k, v in SORT_OPTIONS.items()
        ]
        context["categories"] = self.get_category_choices()
        return context


@method_decorator(login_not_required, name="dispatch")
class BookListView(BookQueryMixin, ListView):
    """
    Public catalogue shelf list view with pagination, filters, and search.
    """

    model = Book
    template_name = "catalog/book_list.html"


@method_decorator(login_not_required, name="dispatch")
class CategoryBookListView(BookQueryMixin, ListView):
    """
    Filtered catalogue listing for a single subject heading.
    """

    model = Book
    template_name = "catalog/book_list.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.category = get_object_or_404(Category, slug=self.kwargs["slug"])

    def base_queryset(self):
        return Book.objects.filter(is_active=True, category=self.category)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category"] = self.category
        return context


@method_decorator(login_not_required, name="dispatch")
class BookDetailView(DetailView):
    """
    Book detail page displaying metadata, ratings, loan status, digital reading room,
    and student review submission form.
    """

    model = Book
    template_name = "catalog/book_detail.html"
    context_object_name = "book"

    def get_queryset(self):
        return (
            Book.objects.all()
            .select_related("category")
            .prefetch_related("reviews__student")
        )

    def get_existing_review(self, user):
        if user.is_authenticated and user.is_student:
            return self.object.reviews.filter(student=user).first()
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        book = self.object
        user = self.request.user

        existing_review = self.get_existing_review(user)
        context["existing_review"] = existing_review

        # Student review form handling
        if user.is_authenticated and user.is_student:
            context["form"] = kwargs.get("form") or ReviewForm(
                instance=existing_review,
                book=book,
                student=user,
            )
        else:
            context["form"] = None

        # Digital Access / Borrow-to-Read checks
        has_active_loan = False
        if user.is_authenticated:
            has_active_loan = BorrowRecord.objects.filter(
                student=user,
                book=book,
                returned_date__isnull=True,
            ).exists()

        can_read_digital = bool(
            user.is_authenticated
            and (user.is_librarian or user.is_superuser or has_active_loan)
        )

        context["has_active_loan"] = has_active_loan
        context["can_read_digital"] = can_read_digital
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        if not (user.is_authenticated and user.is_student):
            messages.error(request, "Only registered student members may submit reviews.")
            return redirect(self.object.get_absolute_url())

        existing_review = self.get_existing_review(user)
        form = ReviewForm(
            request.POST,
            instance=existing_review,
            book=self.object,
            student=user,
        )

        if form.is_valid():
            review = form.save()
            if existing_review:
                messages.success(request, "Your review has been updated.")
            else:
                messages.success(request, "Thank you! Your review has been posted.")
            return redirect(self.object.get_absolute_url())

        return self.render_to_response(
            self.get_context_data(form=form)
        )
