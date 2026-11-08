"""One Hypothesis profile for every fuzz test: deterministic, bounded and cheap.

CI runs pytest under coverage with a 60 s limit per test, on Python 3.13 and 3.14. So the
examples are derived from a fixed seed (``derandomize``: the same inputs on every run and every
Python), their number is capped, no example database is read or written, and the per-example
deadline is explicit instead of left to Hypothesis's default.
"""

import atexit
import shutil
import tempfile
from datetime import timedelta

from hypothesis import HealthCheck, settings
from hypothesis.configuration import set_hypothesis_home_dir

PROFILE = "fastfoto"
MAX_EXAMPLES = 60
DEADLINE = timedelta(seconds=5)  # an example that takes longer is a time-bound bug

# Hypothesis keeps its caches (unicode tables, constants) in a home directory, by default
# ``.hypothesis/`` in the current directory, which is the checkout. Keep them in a temporary one.
HOME_DIR = tempfile.mkdtemp(prefix="hypothesis-home-")
set_hypothesis_home_dir(HOME_DIR)
atexit.register(shutil.rmtree, HOME_DIR, ignore_errors=True)

settings.register_profile(
    PROFILE,
    max_examples=MAX_EXAMPLES,
    derandomize=True,
    deadline=DEADLINE,
    database=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(PROFILE)
