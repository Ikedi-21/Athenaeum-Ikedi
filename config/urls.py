"""
Root URL configuration for Athenaeum Ikedi.

Each app owns its own patterns and is included here under a prefix, rather
than every route in the project being listed in one file. That way a name
such as book_list belongs to the catalog namespace and cannot collide with
anything else, and an app can rearrange its own addresses without this file
being touched.

Prefixes are chosen to read as plain English in the address bar:
/books/ for the catalogue, /loans/ for borrowing, /dashboard/ for the panel
a member sees after signing in, /accounts/ for everything to do with
identity.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve


@login_not_required
def serve_media(request, path, **kwargs):
    """
    Serve an uploaded book cover during development.

    Django's runserver serves static files itself, before any middleware
    runs, but uploaded media is routed like an ordinary view, so
    LoginRequiredMiddleware would demand a login for every cover image and
    the browsable catalogue would show nothing but broken pictures to a
    visitor who is not signed in.

    Django's own serve view is wrapped in this small function rather than
    being marked exempt directly, because login_not_required works by
    setting an attribute on the function it is given, and doing that to
    Django's own shared function would be a side effect on code this
    project does not own.

    Nothing here runs in production: static() below returns an empty list
    when DEBUG is False, and a real deployment has the web server handle
    these files.
    """
    return serve(request, path, **kwargs)


urlpatterns = [
    path("admin/", admin.site.urls),
    # The landing page. There is no model behind it, so it is a plain
    # TemplateView here rather than an almost empty view inside one of the
    # apps. as_view returns a new function each time it is called, so
    # marking this one exempt affects nothing else.
    path(
        "",
        login_not_required(
            TemplateView.as_view(template_name="pages/home.html")
        ),
        name="home",
    ),
    path("accounts/", include("accounts.urls")),
    path("books/", include("catalog.urls")),
    path("catalog/", RedirectView.as_view(url="/books/", permanent=True)),
    path("loans/", include("circulation.urls")),
    path("dashboard/", include("dashboard.urls")),
    # Top-level direct aliases
    path("settings/", RedirectView.as_view(url="/accounts/settings/", permanent=False), name="settings"),
    path("privacy/", RedirectView.as_view(url="/accounts/privacy/", permanent=False), name="privacy"),
    path("terms/", RedirectView.as_view(url="/accounts/terms/", permanent=False), name="terms"),
    path("security/", RedirectView.as_view(url="/accounts/security/", permanent=False), name="security"),
]

# Uploaded covers, development only. static() checks DEBUG itself and
# returns nothing when it is False, so this cannot leak into production
# even if the check below were removed.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        view=serve_media,
        document_root=settings.MEDIA_ROOT,
    )
