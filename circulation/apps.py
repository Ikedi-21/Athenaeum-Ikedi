"""
App configuration for circulation.

The only reason this file is not the one Django generated is the ready()
hook, which is what connects the audit signal receivers.
"""

from django.apps import AppConfig


class CirculationConfig(AppConfig):
    """
    Configuration for the app that handles loans, reservations and fines.

    default_auto_field is deliberately absent. DEFAULT_AUTO_FIELD in
    settings already sets BigAutoField for the whole project, so repeating
    it here would be one more place to keep in step for no gain.
    """

    name = "circulation"

    def ready(self):
        """
        Connect the audit signal receivers, once, at startup.

        Importing signals.py is what runs the @receiver decorators in it,
        and until they run Django knows nothing about them. This is the
        documented place to do it: ready() is called after the app registry
        is fully populated, so the receivers can name models from other
        apps without any import order to think about.

        The import sits inside the method rather than at the top of the
        file on purpose. This module is imported while the registry is
        still being built, and a model import at that point is what raises
        AppRegistryNotReady.

        noqa because a linter is right to be suspicious of an import whose
        name is never used. The import itself is the whole point here, since
        what is wanted is the side effect of the decorators running.
        """
        from . import signals  # noqa: F401
