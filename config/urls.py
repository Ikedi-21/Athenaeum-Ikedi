"""
Root URLconf for Athenaeum Ikedi.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView


@method_decorator(login_not_required, name="dispatch")
class LandingPageView(TemplateView):
    template_name = "pages/home.html"


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", LandingPageView.as_view(), name="home"),
    path("catalog/", include("catalog.urls")),
    path("loans/", include("circulation.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
]

# Serve user uploaded media files during local development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
