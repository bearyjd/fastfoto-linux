"""The columns of a plan file, shared by the code that writes plans and the code that guards it."""

PLAN_COLUMNS = (
    "path",
    "action",
    "rotate_cw",
    "old_tag",
    "new_tag",
    "score",
    "reason",
    "size",
    "mtime_ns",
    "sha256",
)
