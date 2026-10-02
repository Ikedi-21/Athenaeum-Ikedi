"""
Marks this directory as a package so Django can find the tag library in it.

Django's template engine looks for a templatetags package inside every
installed app, and a directory without this file is not a package, so the
library would simply never be found and {% load catalog_extras %} would fail
with a message about it not existing.
"""
