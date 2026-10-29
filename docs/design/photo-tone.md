# Photo tone adjustments

The photo editor adds Brightness and Contrast (-50 through 50), Saturation (-100 through
100), and Adjustment strength (0 through 100). The first three default to zero; strength
defaults to 100. At full adjustment strength, Saturation -100 makes equal RGB channels.

These controls follow accepted red-eye correction and white balance. Adjustment strength affects tone alone;
zero keeps the eye-corrected RGB pixels exactly before JPEG encoding. Neutral brightness, contrast and saturation are
an exact no-op at every strength. Reset adjustments restores neutral values in one undoable
action and preserves eyes. The page Reset restores the complete recipe as it was opened.

## Source, preview and saving

The source is the retained cropped, upright JPEG, not raw scanner data or the enhanced copy.
Detection and stored masks use source coordinates. Changing tone never redetects eyes.
Preview renders full-resolution pixels before resizing. Each render starts from the retained
source, so repeated edits do not accumulate JPEG re-encoding. Save new copy writes a new
numbered JPEG and JSON pair, preserving existing source/output hash and publication checks.

The existing EXIF, XMP, DPI and available ICC preservation contract applies. This stage edits
stored RGB values; it does not convert profiles, measure physical luminance, implement RAW
exposure or recover clipped detail. Global tone changes may intentionally affect every pixel.

## Versioned pixel behavior

Algorithm `photo-tone-v1` keeps the existing `redeye-v1` correction stage, then uses float64
RGB arithmetic. Let `u` be the corrected byte channels divided by 255 and `b,c,s,a` the four
integer controls:

```text
v = (u + b/200 - 0.5) * (1 + c/100) + 0.5
L = 0.2126*v.R + 0.7152*v.G + 0.0722*v.B
t = L + (v - L) * (1 + s/100)
mixed = u + (a/100) * (t - u)
output = uint8(floor(255 * clip(mixed, 0, 1) + 0.5))
```

There is no intermediate clipping. Final conversion clips and rounds half upward. The gray
weights define an encoded-RGB proxy, not a calibrated luminance measurement. Neutral and
zero-strength cases bypass arithmetic for exact identity. Temporary float arrays are bounded
to tiles of at most 262,144 pixels, with cancellation checks between tiles. Tile boundaries
must not change output pixels. JPEG bytes may differ between encoder versions.

## Recipe compatibility

New drafts use schema 2 / `photo-tone-v1` and an exact four-field `tone` object. Schema 1 /
`redeye-v1` remains readable with implicit neutral tone and its original identity. An effective
tone change upgrades a new immutable draft; Undo can restore the legacy draft. Existing saved
files are never rewritten in place. A version-2 draft stays version 2 when returned to neutral.
Decision: an update upgrades a schema-1 draft whenever the stored tone object differs, so a
strength-only change with the other controls neutral also upgrades it to schema 2, although the
picture is unchanged (strength has no effect while the controls are neutral).
Older app versions reject version-2 recipes; the derivative JPEG remains a normal image.

The public immutable `PhotoTone` and pure `update_tone(recipe, tone)` API enforce genuine
integer ranges. `PhotoEditRecipe.tone` is keyword-only; existing positional arguments retain
their meaning. Unknown fields, invalid schema/algorithm pairs, malformed source/mask data and
identity mismatches remain errors. Stored controls, source and exact eye masks replay without
rerunning detection. Synthetic fixtures establish these behaviors, not real-photo quality gains.
