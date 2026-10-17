"""The last check on every strip a trim would remove (constants of the band net)."""

SHADOW_STRIP_MM = 1.5  # the shadow's specks are forgiven in this much of the strip next to the cut
SHADOW_CLUSTER_MM = 2.0  # a cluster of shadow tone is a speck only when it is shorter than this
DUST_MM = 0.5  # a pale cluster shorter than this, anywhere in the strip, is dust
DUST_TOLERANCE = 50  # and pale means this near the backing colour (RGB, any hue)
