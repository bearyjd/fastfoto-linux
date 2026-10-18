"""Immutable document review values and edits."""


def review_items(state):
    raise NotImplementedError


def review_summary(state):
    raise NotImplementedError


class ReviewState:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError
