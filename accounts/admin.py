"""
Admin registration for the custom user model.

Django will not show a swapped in user model in the admin by itself, and
even once registered its own UserAdmin would hide the role field, because
UserAdmin names every field it displays explicitly rather than showing
whatever the model happens to have. Subclassing it and adding role is
what makes the field editable, which matters because promoting a student
to librarian is the only way a librarian account can be created after the
first superuser.

UserAdmin is subclassed rather than replaced so that the password stays
handled properly: it renders as a read only hash with a link to a change
form, never as a text input holding the real value, and the create form
runs the password validators and the Argon2 hasher.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LibraryUserAdmin(UserAdmin):
    """
    The admin for library members.

    Note that admin access itself is still governed by is_staff, which is
    a separate thing from role. A librarian created through this project's
    own pages has role librarian and is_staff False, so they use the
    librarian dashboard rather than this admin. That is intentional: the
    admin is a maintenance tool for whoever runs the installation, not the
    day to day interface for library staff.
    """

    # Editing an existing account. Role is given its own section rather
    # than being dropped in beside first and last name, because it is the
    # one field on this page that changes what somebody is allowed to do.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal details", {"fields": ("first_name", "last_name", "email")}),
        (
            "Library role",
            {
                "fields": ("role",),
                "description": (
                    "Librarians can manage the catalogue and process "
                    "returns. Students borrow books."
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Creating an account from here. usable_password comes from Django's
    # AdminUserCreationForm and offers to create the account with no usable
    # password at all, which is how an account meant for a future password
    # reset invitation is set up. email, the names and role are added to
    # Django's default of username and the two password fields.
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "email",
                    "role",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    # role is worth having in the list and in the filter sidebar, since
    # "show me every librarian" is the first question anyone asks here.
    list_display = (
        "username",
        "get_full_name",
        "email",
        "role",
        "is_active",
        "is_staff",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)
