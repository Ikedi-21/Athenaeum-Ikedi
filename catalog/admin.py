"""
Admin registration for the catalog app.
"""

from django.contrib import admin
from .models import Book, Category, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "book_count")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}

    def book_count(self, obj):
        return obj.books.count()


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "isbn",
        "category",
        "quantity",
        "available_quantity",
        "is_active",
        "added_date",
    )
    list_filter = ("category", "is_active", "published_date")
    search_fields = ("title", "author", "isbn", "description")
    readonly_fields = ("added_date",)
    fieldsets = (
        ("Bibliographic details", {
            "fields": ("title", "author", "isbn", "category", "published_date", "description", "cover_image")
        }),
        ("Circulation & Stock", {
            "fields": ("quantity", "available_quantity", "is_active")
        }),
        ("Digital Access", {
            "fields": ("digital_file", "digital_url")
        }),
        ("Metadata", {
            "fields": ("added_date",)
        }),
    )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("book", "student", "rating", "created_date")
    list_filter = ("rating", "created_date")
    search_fields = ("book__title", "student__username", "comment")
    readonly_fields = ("created_date",)
