"""
Field level validators for the catalog app.

These live in their own module rather than inside models.py because a
validator attached to a model field is referenced by import path in every
migration that touches that field. Giving it a stable home means the
migration history never breaks when models.py is reorganised.
"""

import re

from django.core.exceptions import ValidationError


def bare_isbn(value):
    """
    An ISBN reduced to the characters that actually carry meaning.

    Hyphens and spaces in an ISBN are visual grouping. The same book is
    written 978-0-385-47454-2 on one cover and 9780385474542 on the next,
    and both are the same number.

    Three separate pieces of the project need to agree on that, which is
    why this is a function and not three copies of one regular expression.
    The validator below uses it before checking the check digit. The book
    form uses it to store one canonical form, so the unique constraint on
    the column really does catch the same book entered twice. And the
    search box uses it so that typing the hyphens, or leaving them out,
    finds the book either way.

    Upper cased because an ISBN 10 may end in X standing for the value ten,
    and a lower case x is the same character to everyone except a database
    doing an exact comparison.
    """
    return re.sub(r"[\s-]", "", value).upper()


def validate_isbn(value):
    """
    Accept a valid ISBN 10 or ISBN 13 and reject anything else.

    Checking only the length would happily accept thirteen arbitrary
    digits, so this verifies the check digit as well. The check digit is
    the final character and is calculated from the ones before it, which
    is what catches a typo or a transposed pair. Hyphens and spaces are
    stripped first because they are only visual grouping, not part of the
    number itself.
    """
    digits = bare_isbn(value)

    if len(digits) == 10:
        _validate_isbn10(digits)
    elif len(digits) == 13:
        _validate_isbn13(digits)
    else:
        raise ValidationError(
            "An ISBN has 10 or 13 digits once hyphens are removed. "
            "This one has %(count)s.",
            params={"count": len(digits)},
            code="isbn_length",
        )


def _validate_isbn10(digits):
    """
    Validate the older 10 character form.

    Each character is multiplied by a weight counting down from 10 to 1,
    the results are added together, and a valid ISBN 10 leaves no
    remainder when that total is divided by 11. The last character may be
    an X, which stands for the value 10.
    """
    # Nine digits followed by one digit or an X. The pattern also stops an
    # X appearing anywhere except the final position.
    if not re.fullmatch(r"\d{9}[\dX]", digits):
        raise ValidationError(
            "An ISBN 10 must be nine digits followed by a digit or an X.",
            code="isbn10_format",
        )

    total = 0
    for position, char in enumerate(digits):
        value = 10 if char == "X" else int(char)
        total += value * (10 - position)

    if total % 11 != 0:
        raise ValidationError(
            "That ISBN 10 fails its check digit, so one of the numbers is "
            "wrong or two of them are the wrong way round.",
            code="isbn10_checksum",
        )


def _validate_isbn13(digits):
    """
    Validate the current 13 character form.

    Weights alternate between 1 and 3 reading from the left, the weighted
    values are added together, and a valid ISBN 13 divides exactly by 10.
    """
    if not digits.isdigit():
        raise ValidationError(
            "An ISBN 13 must be digits only.",
            code="isbn13_format",
        )

    # enumerate gives position 0 for the first character, so even
    # positions take weight 1 and odd positions take weight 3.
    total = sum(
        int(char) * (1 if position % 2 == 0 else 3)
        for position, char in enumerate(digits)
    )

    if total % 10 != 0:
        raise ValidationError(
            "That ISBN 13 fails its check digit, so one of the numbers is "
            "wrong or two of them are the wrong way round.",
            code="isbn13_checksum",
        )
