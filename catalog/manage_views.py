"""
The librarian's side of the catalogue: adding, editing, withdrawing and
restoring books, and managing the subject headings they are filed under.

Separate from views.py for two reasons. The public views there are marked
login_not_required and these must never be, so keeping them in different
modules and out of one inheritance chain means that decorator cannot arrive
here by accident. And the two files have different readers: one is the
shelf a visitor browses, the other is library administration.

Every view below is behind LibrarianRequiredMixin, which sends a signed out
visitor to the login page and answers a signed in student with a 403.

There is no view here that deletes a book. Withdrawing is what removal
means in a library that keeps its loan history, and the one place a row can
genuinely be destroyed is the admin site, where the pre_delete signal still
records who did it.
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from accounts.mixins import LibrarianRequiredMixin
from circulation.models import Reservation, ReservationStatus
from circulation.services import cancel_reservation, refresh_queue

from .forms import BookForm, CategoryForm
from .models import Book, Category
from .views import BookQueryMixin


# ------------------------------------------------------------------ #
# Books                                                              #
# ------------------------------------------------------------------ #


class BookManageListView(LibrarianRequiredMixin, BookQueryMixin, ListView):
    """
    The whole catalogue, withdrawn books included, with the same search,
    filter and sort controls the public list has.

    Reusing BookQueryMixin is the point of it existing. A librarian looking
    for the book they need to correct searches the way a reader does, and
    the two lists cannot disagree about what a search means.
    """

    model = Book
    template_name = "catalog/book_manage_admin.html"

    def base_queryset(self):
        """
        Every book, including the ones taken out of the lending collection.

        This is the difference between this page and the public one. A
        withdrawn book has to be reachable or it could never be restored,
        and it would sit in the database invisible to the only people who
        could do anything about it.
        """
        return Book.objects.all()

    def get_category_choices(self):
        """
        The same dropdown, counting every book rather than only lent ones.

        The public version excludes withdrawn books, because a reader
        choosing a category should find as many cards as the number
        promised. Here the promise is different: this list shows withdrawn
        books, so the count has to include them or it would contradict the
        page it sits on.
        """
        return Category.objects.annotate(book_count=Count("books"))


class BookCreateView(LibrarianRequiredMixin, CreateView):
    """
    Add a book to the catalogue.

    Shares its template with the edit view below, so the two forms cannot
    drift apart in appearance, and tells the template what to call itself
    through the context rather than through two near identical files.
    """

    model = Book
    form_class = BookForm
    template_name = "catalog/book_form_admin.html"

    def get_context_data(self, **kwargs):
        """Wording for the shared template. setdefault so a subclass could
        override it by passing its own."""
        kwargs.setdefault("heading", "Add a book")
        kwargs.setdefault("submit_label", "Add to the catalogue")
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        """
        Put every copy of the new book on the shelf, then save it.

        available_quantity is not on the form, because circulation owns that
        column and a librarian typing into it would contradict the loans on
        record. For a book that did not exist a moment ago the right value
        is not in question: nothing can be on loan before the book exists,
        so the shelf count equals the total.
        """
        form.instance.available_quantity = form.instance.quantity

        # super() saves the row, which is what gives self.object below its
        # primary key, and returns the redirect to the new book's page.
        response = super().form_valid(form)

        messages.success(
            self.request,
            f"{self.object.title} has been added to the catalogue.",
        )
        return response


class BookUpdateView(LibrarianRequiredMixin, UpdateView):
    """
    Correct a book already in the catalogue.

    The interesting part is form_valid, which has to keep the shelf count in
    step with a changed total without ever losing sight of the copies that
    are out on loan.
    """

    model = Book
    form_class = BookForm
    template_name = "catalog/book_form_admin.html"

    def get_queryset(self):
        """
        Withdrawn books are editable too.

        A title with a spelling mistake in it is worth correcting before it
        goes back on the shelf, not after.
        """
        return Book.objects.all()

    def get_context_data(self, **kwargs):
        """Wording for the template shared with the create view."""
        kwargs.setdefault("heading", f"Edit {self.object.title}")
        kwargs.setdefault("submit_label", "Save changes")
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        """
        Back to the book's own page, unless it has none to go back to.

        The public detail view answers a withdrawn book with a 404, so
        sending a librarian who has just edited one there would end a
        successful save on an error page.
        """
        if self.object.is_active:
            return self.object.get_absolute_url()
        return reverse("catalog:book_manage")

    def form_valid(self, form):
        """
        Move the shelf count by however much the total moved.

        A librarian buying two more copies of a book with one out on loan
        should end with three copies owned and two on the shelf. Writing the
        total alone would leave the shelf count untouched and quietly lose
        the two new copies, so the difference is applied here.

        The row is re-read under select_for_update rather than trusted from
        the form, because the number of copies on loan can change between
        the page loading and this save: somebody returns a book at the desk
        while the edit form sits open. Reading it inside the transaction is
        what makes the arithmetic true at the moment it is written rather
        than at the moment the page was drawn.

        The lock does nothing on SQLite, which has one writer at a time
        anyway. It is written for the day this project moves to PostgreSQL,
        where it is the difference between correct and nearly correct.
        """
        with transaction.atomic():
            locked = Book.objects.select_for_update().get(pk=self.object.pk)
            copies_on_loan = locked.quantity - locked.available_quantity
            available = form.cleaned_data["quantity"] - copies_on_loan

            if available < 0:
                # The form checked this against the figure it was drawn
                # with, and a copy has gone out since. The librarian is told
                # rather than the check constraint being handed something it
                # has to refuse.
                form.add_error(
                    "quantity",
                    f"A copy went out while this page was open, so "
                    f"{copies_on_loan} are now on loan. The total cannot be "
                    f"lower than that.",
                )
                return self.form_invalid(form)

            form.instance.available_quantity = available
            self.object = form.save()

        messages.success(
            self.request, f"{self.object.title} has been updated."
        )
        # Redirected by hand rather than through super().form_valid, which
        # would save the form a second time.
        return redirect(self.get_success_url())


class BookWithdrawView(LibrarianRequiredMixin, DetailView):
    """
    Take a book out of the lending collection, after saying what that will
    cost.

    A DetailView with a post method rather than a DeleteView, because
    nothing is deleted. The GET draws a confirmation page naming the copies
    still out on loan and the people still waiting, so the decision is made
    with those facts in view rather than after them.
    """

    model = Book
    template_name = "catalog/book_withdraw_admin.html"
    context_object_name = "book"

    def get_queryset(self):
        """
        Only a book still in the collection can be withdrawn from it.

        An already withdrawn book answers with a 404, which is also what
        stops a second POST from cancelling a second round of reservations
        that no longer exist.
        """
        return Book.objects.filter(is_active=True).select_related("category")

    def waiting_reservations(self):
        """
        Everybody currently in this book's queue, whether they are simply
        waiting or already holding a copy.

        Those two statuses are what "in the queue" means, and the same pair
        appears in circulation's own queue helpers and in the partial unique
        constraint on the table. Three statements of one rule is one too
        many, and a shared constant in circulation would be the tidy fix.
        """
        return Reservation.objects.filter(
            book=self.object,
            status__in=[
                ReservationStatus.WAITING,
                ReservationStatus.NOTIFIED,
            ],
        ).select_related("student")

    def get_context_data(self, **kwargs):
        """
        The two facts that make this decision an informed one.

        borrowed_count is arithmetic on the row rather than a query, since
        the model derives it from the total and the shelf count.
        """
        kwargs.setdefault("copies_on_loan", self.object.borrowed_count)
        kwargs.setdefault("waiting", self.waiting_reservations())
        return super().get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        """
        Withdraw the book, then release everybody waiting for it.

        The order is deliberate. is_active is written first so that
        cancelling a hold cannot hand the freed copy to the next person in
        the queue, which is what would otherwise happen: cancelling a
        notified reservation asks the queue to move along, and a book that
        is no longer lent has nobody to offer it to. The guard in
        offer_available_copies is the other half of that arrangement.

        A copy on loan is left alone. Withdrawing a book is not a demand
        that it be returned early, and the loan carries on as normal until
        somebody brings it back.
        """
        self.object = self.get_object()

        with transaction.atomic():
            book = Book.objects.select_for_update().get(pk=self.object.pk)
            book.is_active = False

            # update_fields names the column so the audit signal can see
            # what changed. is_active is one of the fields it watches, and
            # the change from True to False is what it reports as a
            # withdrawal rather than an ordinary edit.
            book.save(update_fields=["is_active"])

            # Each cancellation is written by the librarian's own hand as
            # far as the audit log is concerned, which is accurate: the
            # student did not give up their place, it was taken.
            released = 0
            for reservation in self.waiting_reservations():
                cancel_reservation(
                    reservation=reservation,
                    actor=request.user,
                    request=request,
                )
                released += 1

        message = f"{book.title} has been withdrawn from the collection."
        if released:
            people = "person was" if released == 1 else "people were"
            message += f" {released} {people} waiting and no longer are."
        messages.success(request, message)
        return redirect("catalog:book_manage")


class BookRestoreView(LibrarianRequiredMixin, SingleObjectMixin, View):
    """
    Put a withdrawn book back into the lending collection.

    No confirmation page, because there is nothing to warn about: this adds
    a book back to the shelves and takes nothing away. The button on the
    management list posts straight here.

    No get method either, which means Django answers a GET with 405 Method
    Not Allowed. That is the intended behaviour and not an omission. A
    change of state should not be something a link can do, because anything
    that follows links, a browser prefetching or a crawler, would then be
    able to restore books by reading pages.
    """

    model = Book

    def get_queryset(self):
        """
        Only a withdrawn book can be restored, so anything else is a 404.

        This makes the button idempotent in the way that matters: a second
        press, or a refresh of the redirect, cannot repeat the work.
        """
        return Book.objects.filter(is_active=False)

    def post(self, request, *args, **kwargs):
        """Mark the book lendable again and let the queue catch up."""
        book = self.get_object()

        with transaction.atomic():
            locked = Book.objects.select_for_update().get(pk=book.pk)
            locked.is_active = True
            # Named so the audit signal records the restoration.
            locked.save(update_fields=["is_active"])

            # Nobody can join the queue for a withdrawn book, so this queue
            # should be empty and this call should do nothing. It is made
            # anyway, because "should be empty" is an assumption and this is
            # the one line that makes it not matter whether it holds.
            refresh_queue(locked, request=request)

        messages.success(
            request,
            f"{locked.title} is back in the lending collection.",
        )
        return redirect("catalog:book_manage")


# ------------------------------------------------------------------ #
# Subject headings                                                   #
# ------------------------------------------------------------------ #


class CategoryManageListView(LibrarianRequiredMixin, ListView):
    """
    Every subject heading, with what is filed under it.

    Two counts rather than one, because they answer different questions. A
    heading with twelve books of which none are currently lent is not the
    same as an empty heading, and a librarian deciding whether a heading is
    still needed wants to see both numbers.
    """

    model = Category
    template_name = "catalog/category_manage_admin.html"
    context_object_name = "categories"

    def get_queryset(self):
        """
        The headings in name order, counted.

        Both counts ride on one join, so neither needs distinct: there is
        nothing else multiplying the rows. The ordering comes from
        Category.Meta and is not repeated here.
        """
        return Category.objects.annotate(
            book_count=Count("books"),
            lendable_count=Count("books", filter=Q(books__is_active=True)),
        )


class CategoryCreateView(LibrarianRequiredMixin, CreateView):
    """
    Add a subject heading.

    The slug is not on the form. Category.save builds it from the name, and
    the form refuses a name that would collide with an existing slug, so
    nothing here has to think about web addresses.
    """

    model = Category
    form_class = CategoryForm
    template_name = "catalog/category_form_admin.html"

    # reverse_lazy rather than reverse, because a module level reverse runs
    # while this file is being imported, which is before the URL patterns
    # exist to be reversed against.
    success_url = reverse_lazy("catalog:category_manage")

    def get_context_data(self, **kwargs):
        """Wording for the template shared with the edit view."""
        kwargs.setdefault("heading", "Add a category")
        kwargs.setdefault("submit_label", "Add category")
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        """Save, then say so on the page the librarian lands on."""
        response = super().form_valid(form)
        messages.success(
            self.request, f"The category {self.object.name} has been added."
        )
        return response


class CategoryUpdateView(LibrarianRequiredMixin, UpdateView):
    """
    Rename a subject heading or reword its description.

    Renaming leaves the slug alone, on purpose, so the address of the
    category page survives a correction to its spelling. That decision lives
    in Category.save and is explained there.
    """

    model = Category
    form_class = CategoryForm
    template_name = "catalog/category_form_admin.html"
    success_url = reverse_lazy("catalog:category_manage")

    def get_context_data(self, **kwargs):
        """Wording for the template shared with the create view."""
        kwargs.setdefault("heading", f"Edit {self.object.name}")
        kwargs.setdefault("submit_label", "Save changes")
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        """Save, then say so on the page the librarian lands on."""
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"The category {self.object.name} has been updated.",
        )
        return response
