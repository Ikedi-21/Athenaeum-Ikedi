"""
URL patterns for the catalogue.

Two of these names are referenced from catalog/models.py, by
Book.get_absolute_url and Category.get_absolute_url, so those two are fixed
and everything else was named to match their style.

The public pages sit at the top level and every librarian page sits under
manage/, which is a convention worth keeping: one glance at an address says
whether it needs a librarian, and the permission mixin on the view is what
enforces it rather than the prefix itself.
"""

from django.urls import path

from . import manage_views, views

app_name = "catalog"

urlpatterns = [
    # ---------------------------------------------------------------- #
    # Public
    # ---------------------------------------------------------------- #
    # The shelf list, which is also where logging out lands. The search,
    # category and sort controls all arrive here as query string values, so
    # they need no patterns of their own.
    path("", views.BookListView.as_view(), name="book_list"),
    # One book, and where a review is posted to. The primary key is used
    # rather than a slug because two different books can share a title, and
    # an ISBN is not something a reader would recognise in an address bar
    # either way.
    path("<int:pk>/", views.BookDetailView.as_view(), name="book_detail"),
    # Books in one category. This sits under its own prefix so that a
    # category whose slug happens to be numeric cannot be confused with a
    # book primary key by the pattern above.
    path(
        "category/<slug:slug>/",
        views.CategoryBookListView.as_view(),
        name="category_detail",
    ),
    # ---------------------------------------------------------------- #
    # Librarian
    # ---------------------------------------------------------------- #
    # The whole catalogue including withdrawn books, searchable the same way
    # the public list is.
    path(
        "manage/",
        manage_views.BookManageListView.as_view(),
        name="book_manage",
    ),
    path(
        "manage/add/",
        manage_views.BookCreateView.as_view(),
        name="book_add",
    ),
    path(
        "manage/<int:pk>/edit/",
        manage_views.BookUpdateView.as_view(),
        name="book_edit",
    ),
    # A confirmation page on GET, the withdrawal itself on POST.
    path(
        "manage/<int:pk>/withdraw/",
        manage_views.BookWithdrawView.as_view(),
        name="book_withdraw",
    ),
    # POST only, so this name belongs in a form and never in a link.
    path(
        "manage/<int:pk>/restore/",
        manage_views.BookRestoreView.as_view(),
        name="book_restore",
    ),
    # Subject headings. Nested under manage/ rather than sitting beside
    # category/<slug>/ above, because that one is a reader's page and these
    # are not.
    path(
        "manage/categories/",
        manage_views.CategoryManageListView.as_view(),
        name="category_manage",
    ),
    path(
        "manage/categories/add/",
        manage_views.CategoryCreateView.as_view(),
        name="category_add",
    ),
    path(
        "manage/categories/<int:pk>/edit/",
        manage_views.CategoryUpdateView.as_view(),
        name="category_edit",
    ),
]
