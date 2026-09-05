"""
URL patterns for the dashboard.

dashboard:home is what LOGIN_REDIRECT_URL in settings.py points at, so
this name has to resolve for a login to complete.
"""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
]
