"""
Template filters for the catalogue.

Both of these turn a rating into something a page can draw. They exist as
filters rather than as work done in a view because the number arrives from an
annotation, Avg("reviews__rating"), and every list and detail page that shows
a book has to present it the same way. A filter is the one place that
formatting can live without either being repeated in five templates or
turning a queryset into a list of dictionaries on the way out of a view.

Neither filter trusts what it is given. average_rating is None for a book
nobody has reviewed, and a template can just as easily hand these a string,
so both answer an unusable value with something harmless instead of raising.
A page half drawn and then abandoned mid tag is a worse outcome than a
missing star.

Load with {% load catalog_extras %}.
"""

import math

from django import template

register = template.Library()

# The two glyphs the star row is drawn from. Kept here rather than inline so
# that swapping to a different pair, or to an image, is one edit.
FILLED_STAR = "★"
EMPTY_STAR = "☆"

# Ratings run from one to five, which is enforced by a validator and a check
# constraint on Review.rating. Both filters below clamp to this anyway,
# because an average is arithmetic and arithmetic can be handed anything.
MAX_RATING = 5


def _as_number(value):
    """
    Read a rating as a float, or return None if it cannot be read as one.

    Shared by both filters. None arrives from the annotation for a book with
    no reviews, a string can arrive from a template variable, and a Decimal
    arrives from some database backends, so all three are handled in one
    place. TypeError covers None and objects that are not numbers at all,
    ValueError covers strings that are not numbers.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@register.filter(is_safe=True)
def stars(value):
    """
    Turn a rating into five characters, filled then empty.

    A rating of 4 gives four filled stars and one empty one, and 4.2 gives
    the same, because the row is a glance rather than a measurement. Rounding
    is half up, done by adding a half and taking the floor: Python's own
    round() rounds a half to the nearest even number, so round(4.5) is 4 and
    round(3.5) is 4, which is correct for statistics and surprising on a
    page.

    A book with no reviews gives an empty string rather than five empty
    stars, so the template can say "Not yet rated" instead of showing a row
    that looks like a rating of nothing.

    The result is a run of glyphs and not a sentence, so a screen reader
    reading it aloud says "white star white star" and means nothing by it.
    Templates using this must mark the glyphs aria-hidden="true" and put the
    number next to them in text, which is what the pages in this project do.

    is_safe=True says this filter introduces no HTML of its own, which is
    true: it returns two characters in some arrangement and never passes its
    input through, so nothing it returns can carry markup in from elsewhere.
    """
    number = _as_number(value)
    if number is None:
        return ""

    # Half up, then held inside the one to five the scale allows.
    filled = math.floor(number + 0.5)
    filled = max(0, min(MAX_RATING, filled))

    return FILLED_STAR * filled + EMPTY_STAR * (MAX_RATING - filled)


@register.filter
def rating_percent(value):
    """
    Turn a rating into a whole percentage of five.

    This is what a star bar drawn in CSS needs: one row of grey stars with a
    row of gold ones laid over it, clipped to a width. Unlike the filter
    above it keeps the fraction, since a bar can show four fifths of a star
    and a glyph cannot, so 4.2 gives 84 and the bar is honest about it.

    Returned as an int so that a template writes width: {{ x }}% and gets
    84%, not 84.0%. A book with no reviews gives 0, which is a bar of no
    width, which is the truthful picture.
    """
    number = _as_number(value)
    if number is None:
        return 0

    percent = round(number / MAX_RATING * 100)
    return max(0, min(100, percent))
