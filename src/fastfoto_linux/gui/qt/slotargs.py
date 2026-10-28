"""Strict argument checks for QML calls that confirm something destructive."""


def confirmed_flag(value: object) -> bool:
    """``value`` if QML passed a real boolean; anything else (such as "false") is refused.

    A ``@Slot(bool)`` call converts a string with Python truthiness, so ``"false"`` would count as
    a confirmation. Destructive slots take a ``QVariant`` and check the type here instead.
    """
    if type(value) is not bool:
        raise ValueError("The confirmation was not a yes or no answer, so nothing was changed.")
    return value
