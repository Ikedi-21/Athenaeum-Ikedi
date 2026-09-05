"""
Makes the request being handled visible to code that was never handed it.

Almost everything in this project passes the request down explicitly, which
is the honest way to do it: services.py takes request=None and the views
supply it. But signal receivers cannot work that way. Django calls a
receiver with the model instance and nothing else, so when a librarian
edits a book in the admin there is no argument anywhere in the call that
says who did it.

This module closes that one gap. The middleware puts the request in a
context variable on the way in and takes it out again on the way out, and
signals.py reads it with get_current_request().

Nothing else should read it. Reaching for the request from deep inside code
that was not given one is hidden coupling, and it makes a function's
behaviour depend on something invisible in its signature. It is worth it
here only because the alternative is an audit log that cannot name the
person who changed the catalogue.
"""

import contextvars

# A context variable rather than threading.local, which is the older way of
# doing this and would be a real bug here.
#
# Under WSGI one thread handles one request at a time, so a thread local
# would work. Under ASGI, which Django 6 runs happily and which this project
# may well be deployed on, a single thread interleaves many coroutines. Two
# requests being served on the same thread would share one thread local, and
# the audit log would start attributing one member's actions to another.
#
# A context variable is scoped to the current context instead of the current
# thread, and asyncio gives every task its own copy of the context, so the
# two requests cannot see each other's value.
#
# default=None means get() never raises LookupError, so a receiver that
# fires outside a request, from a management command, a test, or a data
# migration, simply reads None and logs an entry with no user attached.
_current_request = contextvars.ContextVar(
    "athenaeum_current_request",
    default=None,
)


def get_current_request():
    """
    The request being handled right now, or None if there is not one.

    None is a normal answer, not a failure. Fixtures load, management
    commands run, and tests call model.save() directly, and in all three
    cases nobody is signed in because there is no browser involved.
    Callers are expected to cope with None rather than assume a request.
    """
    return _current_request.get()


class AuditContextMiddleware:
    """
    Stores the request for the duration of the view, then clears it.

    Placed after AuthenticationMiddleware in settings.MIDDLEWARE, because
    the only reason to keep the request is to read request.user off it, and
    that attribute does not exist until AuthenticationMiddleware has run.
    """

    def __init__(self, get_response):
        """
        Called once when the server starts, not once per request.

        Django hands each middleware the next thing in the chain, and the
        object built here is reused for every request the process serves.
        That reuse is exactly why __call__ below has to clean up after
        itself: this instance outlives the request, so anything left behind
        on it, or in a variable it wrote to, would still be there when the
        next person arrives.
        """
        self.get_response = get_response

    def __call__(self, request):
        """
        Set the variable, handle the request, and always put it back.

        set() returns a token that remembers what the variable held before,
        and reset(token) restores precisely that. Restoring the previous
        value rather than blanking it is what makes this safe to nest: if
        anything ever wraps one request inside another, unwinding puts back
        the outer request instead of losing it.

        The try and finally is the security part of this file. Without it,
        a view that raises would leave one member's request sitting in the
        variable, and the next request served by that worker, before its own
        set() ran, could read it. An audit log that names the wrong person
        is worse than one that names nobody, so the reset happens whether
        the view returned a page, raised PermissionDenied, or crashed.
        """
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
