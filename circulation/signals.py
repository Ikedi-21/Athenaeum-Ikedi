"""
Audit entries for the things that happen where no view of ours is running.

services.py already logs every circulation operation, because every one of
those goes through a function we wrote and can put a line in the log on the
way past. Catalogue work does not. A librarian adds a book through the
admin site, or a superuser changes somebody's role from a shell, and no
code of ours is anywhere on the stack to notice.

Model signals are the one place that does see those saves, so that is
where this file hooks in. It records four things: a book added, a book
edited, a book withdrawn or deleted, and a change to what a user is
allowed to do.

Two habits are worth knowing before reading on.

Who did it comes from middleware.py, because Django hands a receiver the
row and nothing else. Where there is no request, which is the case for
fixtures, management commands and tests, the entry is written with no user
attached rather than skipped, so the log still says the change happened
even when it cannot say who was responsible.

A save is only examined when it could have touched something on the watched
list below. That guard matters because circulation saves books constantly
to move the shelf count, and signing in saves the user to stamp
last_login. Neither is a catalogue edit, and neither belongs in the log
looking like one.
"""

from django.conf import settings
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from catalog.models import Book

from .middleware import get_current_request
from .models import AuditAction
from .services import book_target, record_action

# ------------------------------------------------------------------ #
# What counts as a change worth recording                            #
# ------------------------------------------------------------------ #

# The book columns a librarian could meaningfully edit, mapped to the words
# the log should use for them. The key is the attribute the value is read
# from, so the foreign key appears as category_id: reading that gives the
# integer already sitting on the instance, while reading category would
# fetch the whole Category row from the database just to compare it.
#
# available_quantity is deliberately absent. It is circulation's column,
# moved by borrowing and returning, and every one of those already writes
# its own audit entry. added_date is absent because it never changes.
_BOOK_WATCHED = {
    "title": "title",
    "author": "author",
    "isbn": "ISBN",
    "category_id": "category",
    "published_date": "published date",
    "description": "description",
    "quantity": "total copies",
    "cover_image": "cover image",
    "is_active": "in the lending collection",
}

# The same set spelled the way save(update_fields=...) spells it, which for
# a foreign key is the field name and not the column, so both spellings are
# present. Used only to decide whether a partial save is worth inspecting.
_BOOK_WATCHED_FIELD_NAMES = frozenset(_BOOK_WATCHED) | {"category"}

# What a user may do. role is this project's own permission system, and the
# three flags are Django's, so all four are watched together: quietly
# granting somebody is_superuser is a larger change than editing their role
# and it would be strange for the log to mention one and not the other.
#
# Everything else about a user, including the password, is left out. A
# password change is not a change in what somebody is allowed to do, and
# recording that one happened, next to the username and a timestamp, tells
# an attacker reading the log more than it tells a librarian.
_USER_WATCHED = {
    "role": "role",
    "is_staff": "admin site access",
    "is_superuser": "superuser",
    "is_active": "account enabled",
}
_USER_WATCHED_FIELD_NAMES = frozenset(_USER_WATCHED)

# How much of a value to quote in the log. Long enough to tell two titles
# apart, short enough that editing a book description does not paste the
# whole paragraph twice into a single line.
_MAX_VALUE_LENGTH = 60

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #


def _actor():
    """
    The request being served and the user making it, or a pair of Nones.

    Both are returned together because record_action wants both: the user
    to attribute the entry to, and the request to read the IP address off.

    getattr rather than request.user, because the attribute only exists
    once AuthenticationMiddleware has run. A signal fired from a
    management command has no request at all, and one fired from a
    middleware sitting above the auth middleware would have a request
    without a user. Neither is an error here, and neither should be
    allowed to turn a book edit into a crash.
    """
    request = get_current_request()
    return getattr(request, "user", None), request


def _worth_inspecting(update_fields, watched_field_names):
    """
    Whether a save could have altered anything on the watched list.

    A full save passes update_fields as None, meaning every column was
    written, so there is no way to rule it out and it has to be examined.
    A partial save names its columns, and if none of them is watched the
    receiver can stop immediately without touching the database.

    This is what keeps the log clean and the cost near zero. Signing in
    saves the user to stamp last_login, and a borrow that used save()
    rather than an update() would write available_quantity. Both are
    ordinary bookkeeping, neither is a change anybody made on purpose, and
    both are dismissed here in one set operation.
    """
    if update_fields is None:
        return True
    # isdisjoint rather than building an intersection, because the only
    # question is whether there is any overlap at all.
    return not watched_field_names.isdisjoint(update_fields)


def _snapshot(instance, watched):
    """
    A plain dict of the watched values on a row.

    A dict and not the instance itself, on purpose. Holding onto a model
    would mean holding a live object whose attributes can still trigger
    queries, and it would keep the whole previous row in memory until the
    save finished. The comparison only needs the handful of values, so only
    those are kept.

    The getattr with a default unwraps an ImageField. Reading cover_image
    gives a FieldFile, which is an object bound to the row it came from,
    and all that is wanted is the path it holds. Every other watched value
    is a string, a number, a date or a boolean, none of which has a name
    attribute, so they come through untouched.
    """
    values = {}
    for attname in watched:
        value = getattr(instance, attname)
        values[attname] = getattr(value, "name", value)
    return values


def _readable(value):
    """
    One value, written the way a person reading the log would want it.

    Booleans first, because True and False in a sentence about whether a
    book is in the collection reads like a debugger rather than a record.
    Then the empty cases, which are worth naming: "publication date: empty
    to 1958" says something, while "publication date: None to 1958" says
    the same thing in the language of the implementation.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None or value == "":
        return "empty"
    text = str(value)
    if len(text) <= _MAX_VALUE_LENGTH:
        return text
    # Three full stops rather than the single ellipsis character, so the
    # log stays plain ASCII wherever it is read or exported.
    return text[: _MAX_VALUE_LENGTH - 3] + "..."


def _describe_changes(previous, instance, watched):
    """
    What actually changed, as a list of readable phrases.

    Returning a list rather than a string lets the caller ask the more
    useful question first: an empty list means nothing on the watched list
    moved, which is the signal not to write an entry at all. A save that
    changed only untracked columns produces no log line, which is how a
    borrow avoids leaving a phantom "book edited" behind it.

    Comparison is by value and not by identity, so a form that resubmits
    the same title is correctly treated as no change.
    """
    changes = []
    for attname, label in watched.items():
        before = previous.get(attname)
        after = getattr(instance, attname)
        # The same unwrapping _snapshot does, so a FieldFile is compared
        # against the stored path rather than against an object.
        after = getattr(after, "name", after)
        if before != after:
            changes.append(f"{label}: {_readable(before)} to {_readable(after)}")
    return changes


def user_target(user):
    """
    How a user is described in the audit log.

    The same shape as book_target in services.py, and public for the same
    reason: the id makes the entry unambiguous when two people have similar
    names, and the username keeps it readable a year later without a
    lookup. Because the description is stored as text, the entry still
    makes sense after the account it refers to has been deleted.
    """
    return f"User #{user.pk} {user.username}"


# ------------------------------------------------------------------ #
# Books                                                              #
# ------------------------------------------------------------------ #


@receiver(pre_save, sender=Book, dispatch_uid="circulation_book_before_save")
def remember_book_before_save(
    sender, instance, raw=False, update_fields=None, **kwargs
):
    """
    Read the stored row before the save overwrites it.

    This has to happen in pre_save. By the time post_save runs, the new
    values are in the database and the old ones are gone, so an entry
    written then could say a book was edited but never say what it was
    edited from. The values are stashed on the instance, which is the same
    object post_save is about to be handed, so nothing has to be looked up
    twice or matched by primary key.

    dispatch_uid is what stops the receiver being connected twice. Django
    keys connections by it, so if this module were ever imported a second
    time, by a test that reloads it or a duplicate entry in INSTALLED_APPS,
    the second connect replaces the first instead of adding to it, and one
    edit still produces one log entry.
    """
    # Cleared unconditionally first, because the instance may be a Python
    # object that has been saved before. Leaving a snapshot from the earlier
    # save in place would make the next one report changes against the wrong
    # starting point.
    instance._audit_previous = None
    # raw is True while loaddata is running. Those saves are a fixture being
    # restored, not somebody editing the catalogue, so there is nothing to
    # attribute and nothing worth recording.
    if raw:
        return
    # No primary key means an insert, so there is no previous row to read.
    # post_save is told created=True and handles it from there.
    if instance.pk is None:
        return
    if not _worth_inspecting(update_fields, _BOOK_WATCHED_FIELD_NAMES):
        return
    stored = Book.objects.filter(pk=instance.pk).first()
    # first() rather than get(), because a save can legitimately carry a
    # primary key that is not in the table yet, and refusing to crash on
    # that is worth more than insisting the row must exist.
    if stored is not None:
        instance._audit_previous = _snapshot(stored, _BOOK_WATCHED)


@receiver(post_save, sender=Book, dispatch_uid="circulation_book_after_save")
def log_book_save(
    sender, instance, created=False, raw=False, update_fields=None, **kwargs
):
    """
    Record a book being added, edited, or withdrawn from the collection.

    post_save and not pre_save, because an entry should only exist if the
    change really landed. A save can still fail on a unique ISBN or a check
    constraint, and by the time this runs that has already been survived.

    Withdrawing is separated out from editing rather than left as one more
    changed field, because it is the operation the assignment calls
    deleting a book. Book.is_active exists so that removing a book from
    circulation does not have to destroy the loans that reference it, and
    the log should name that for what it is.
    """
    if raw:
        return
    if not _worth_inspecting(update_fields, _BOOK_WATCHED_FIELD_NAMES):
        return
    user, request = _actor()
    if created:
        # No change list on a new book. Everything about it is new, and the
        # book itself is the record of what the values are.
        record_action(
            AuditAction.BOOK_CREATE,
            book_target(instance),
            user=user,
            request=request,
        )
        return
    previous = getattr(instance, "_audit_previous", None)
    if previous is None:
        # The snapshot is missing, which means the row was not there to read
        # in pre_save. Still logged, because an edit that happened is worth
        # recording even when the log cannot say what it replaced. Silence
        # here would be the one outcome that loses information.
        record_action(
            AuditAction.BOOK_UPDATE,
            book_target(instance),
            user=user,
            detail="Edited. The values before the change were not readable.",
            request=request,
        )
        return
    changes = _describe_changes(previous, instance, _BOOK_WATCHED)
    if not changes:
        # A save that moved nothing on the watched list. This is the second
        # guard against a phantom entry, and the one that catches a full
        # save that passed no update_fields at all.
        return
    withdrawn = previous.get("is_active") and not instance.is_active
    record_action(
        AuditAction.BOOK_WITHDRAW if withdrawn else AuditAction.BOOK_UPDATE,
        book_target(instance),
        user=user,
        detail="; ".join(changes),
        request=request,
    )


@receiver(pre_delete, sender=Book, dispatch_uid="circulation_book_before_delete")
def log_book_delete(sender, instance, **kwargs):
    """
    Record a book being genuinely deleted, not merely withdrawn.

    pre_delete, because the entry describes a row that is about to stop
    existing and the description has to be built while the title and author
    are still readable.

    Writing the entry before the delete succeeds sounds like it risks
    logging something that never happened, and it would if the two were
    separate. They are not: Django performs a delete inside a transaction,
    so if the delete is refused the audit row is rolled back with it. That
    refusal is likely here rather than theoretical, because BorrowRecord
    points at Book with PROTECT, so any book that has ever been lent raises
    ProtectedError instead of being deleted. Which is the intended
    behaviour, and the reason withdrawing exists.

    The detail names the author and the copy count, so the entry still says
    what was lost after the row it refers to is gone.
    """
    user, request = _actor()
    record_action(
        AuditAction.BOOK_DELETE,
        book_target(instance),
        user=user,
        detail=f"By {instance.author}. {instance.quantity} copies on record.",
        request=request,
    )


# ------------------------------------------------------------------ #
# Users                                                              #
# ------------------------------------------------------------------ #

# sender is given as the setting rather than the model class, which is the
# form Django's model signals accept as a lazy reference and resolve once
# the app registry is ready. Two things follow from that. This module never
# imports the user model, so it cannot be the thing that makes an import
# order problem appear, and the project keeps its single source of truth
# for which model is the user model.


@receiver(
    pre_save,
    sender=settings.AUTH_USER_MODEL,
    dispatch_uid="circulation_user_before_save",
)
def remember_user_before_save(
    sender, instance, raw=False, update_fields=None, **kwargs
):
    """
    Read what a user was allowed to do before the save changes it.

    The same shape as the book receiver above and for the same reason: only
    pre_save can still see the old values.

    The attribute name is shared with the book snapshot, which is safe
    because each receiver is registered against one sender and only ever
    sees instances of its own model. A book snapshot is never written onto
    a user or the other way round.

    sender is the resolved model class by the time the signal is dispatched,
    so sender.objects is the user manager and there is no need to import
    the model to run the query.
    """
    instance._audit_previous = None
    if raw or instance.pk is None:
        return
    if not _worth_inspecting(update_fields, _USER_WATCHED_FIELD_NAMES):
        return
    stored = sender.objects.filter(pk=instance.pk).first()
    if stored is not None:
        instance._audit_previous = _snapshot(stored, _USER_WATCHED)


@receiver(
    post_save,
    sender=settings.AUTH_USER_MODEL,
    dispatch_uid="circulation_user_after_save",
)
def log_user_permission_change(
    sender, instance, created=False, raw=False, update_fields=None, **kwargs
):
    """
    Record a change to what somebody is allowed to do.

    This is the entry that matters most on the page. Everything else in the
    log describes a book moving; this describes somebody gaining the ability
    to move every book, clear fines, and read other members' borrowing
    history. Whoever granted it, and when, is the question an audit log
    exists to answer.

    A new account is not logged. Registration grants nothing beyond the
    student role every account starts with, and the account's own
    date_joined already records that it was created.

    Signing in is not logged either, and would be the obvious accident here:
    Django stamps last_login by saving the user, so without the
    update_fields guard every login in the library would appear in the log
    as a permission change.
    """
    if raw or created:
        return
    if not _worth_inspecting(update_fields, _USER_WATCHED_FIELD_NAMES):
        return
    user, request = _actor()
    previous = getattr(instance, "_audit_previous", None)
    if previous is None:
        # Recorded rather than skipped, unlike a book, deliberately. An
        # unexplained permission change is still a permission change, and
        # the one thing that must not happen is for it to leave no trace.
        record_action(
            AuditAction.ROLE_CHANGE,
            user_target(instance),
            user=user,
            detail="Permissions changed. The previous values were not readable.",
            request=request,
        )
        return
    changes = _describe_changes(previous, instance, _USER_WATCHED)
    if not changes:
        return
    record_action(
        AuditAction.ROLE_CHANGE,
        user_target(instance),
        user=user,
        detail="; ".join(changes),
        request=request,
    )
