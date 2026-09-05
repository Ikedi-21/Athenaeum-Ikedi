"""
URL patterns for circulation.

Empty for now, and included from the root URLconf all the same. Declaring
app_name here means the borrowing, returning, renewing and reservation
views can be added in the circulation task without the root URLconf or any
already written template link having to change.
"""

app_name = "circulation"

urlpatterns = []
