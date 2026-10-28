"""The constants of document deskew, in one place (the design doc quotes them; a test pins them)."""

MAX_TENTHS = 100  # the applied angle is within +-10 degrees, in tenths of a degree
MIN_TENTHS = 3  # a smaller estimate is level (0.3 degrees itself applies)
OUTER_MAX_TENTHS = 450  # angles out to this are scored too, to find a second tilt
OUTER_STEP = 5  # tenths between the angles scored beyond the applied range
REFINED_PEAKS = 3  # the highest outer samples searched again in tenths, to either side
CONTENT_DELTA = 40  # the clip check sees everything this much darker than the paper
WORK_DPI = 100  # the estimate is made on a grid of about this resolution
MIN_DPI = 100  # below this resolution the page is not measured
INK_MAX_LEVEL = 200  # a work-grid pixel is ink when darker than min(Otsu, this)
MIN_INK_POINTS = 1500  # fewer ink pixels on the work grid than this: nothing to measure
MAX_INK_PCT = 35  # more ink than this share of the work grid is a photo or a dark page
MAX_POINTS = 250_000  # ink points scored; more are taken by an even stride
SEPARATION_TENTHS = 20  # the confidence looks at angles at least this far from the best
SEPARATION_PCT = 92  # abstain when the best far score is at least this share of the best
CLIP_SLACK_PX = 1  # ink may land this many work pixels outside the frame


def check_tenths(tenths: object) -> int:
    """``tenths`` if it is a whole number (not a bool) within +-``MAX_TENTHS``, else ValueError."""
    if type(tenths) is not int or not -MAX_TENTHS <= tenths <= MAX_TENTHS:
        raise ValueError(
            f"deskew must be a whole number of tenths from -{MAX_TENTHS} to {MAX_TENTHS}"
        )
    return tenths
