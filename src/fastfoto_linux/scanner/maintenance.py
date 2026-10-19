"""Bounded ESC/I-2 maintenance framing; implementation follows recorded RED CI."""

import time

OPERATION_TIMEOUT_S = 15.0
CLEANUP_TIMEOUT_S = 2.0
_clock = time.monotonic
_sleep = time.sleep
