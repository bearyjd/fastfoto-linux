# Synthetic photo-edit fixtures (E00)

Version: 1, 2026-10-18. All image pixels are generated locally by `helpers.py` or the tests.
No downloaded/public image, scanner output, private photograph or model artifact is included.
The generated patterns have no third-party image licensing obligations; repository licensing applies.

The 160 by 100 RGB skin-colored rectangle contains two red circular pupils, a bright protected
highlight, and configurable EXIF orientation/DPI/description/XMP. Coordinates and masks are exact.
Tests exercise accepted/rejected eyes, strength, local changes, manual ellipses, immutable source,
recipe bounds/replay, corrupt identity, cancellation, metadata and failure-safe numbered publication.
300/600 DPI and 90/180-degree EXIF cases cover canonical coordinates; GUI mapping is a separate gate.

These are invariant fixtures, not human photographs or detector-quality ground truth. They cannot
establish real-world precision, recall, identity preservation, skin-tone coverage or perceptual quality.
No auto-correction default changes are justified. A future rights-cleared human-photo evaluation
must have item-level rights, checksums, annotations and a separately frozen held-out partition.
