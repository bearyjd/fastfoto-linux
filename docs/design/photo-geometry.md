# Photo geometry (crop and quarter turns)

The photo editor can crop to a free rectangle and turn the picture in quarter turns. Both are
exact pixel operations: nothing is resampled, there are no aspect presets, and straightening to
an arbitrary angle is not part of this stage.

## Order of operations

Red-eye correction runs first, in source coordinates on the full retained original. The crop
is then cut from that result, the cropped pixels are turned clockwise, and tone is applied
last. Tone is per pixel, so rendering with geometry equals turning and cropping a render that
has none. Every render starts from the retained source, so repeated edits never accumulate
JPEG re-encoding. Eyes are always edited on the whole source; their masks are never moved.

## Recipe schema 3 (`photo-geometry-v1`)

Schema 3 adds a `geometry` object with exactly `quarter_turns` (0 to 3, clockwise) and `crop`
(`null` or `[left, top, right, bottom]`, half-open edges in source pixels). Integers over the
stored source size make the crop exact and pixel aligned, so no rounding rule exists and the
JSON stays byte-identical across round trips.

- A full-frame crop is stored as `null`, so each meaning has one encoding.
- The shortest side allowed is 5 mm at the source's effective DPI (at least one pixel), never
  more than the source. A source smaller than that admits only no crop.
- Schema 1 and 2 files must not contain geometry; they are read and re-serialized unchanged.
- New drafts remain schema 2. Changing geometry upgrades a draft to schema 3, a tone change
  never downgrades it, and a schema 3 draft returned to neutral stays schema 3. Undo restores
  the earlier schema because the editor keeps the earlier recipe object.

## Preview and saved metadata

The preview publishes `before` (source), `after` (the bounded result with geometry) and
`working` (eyes plus tone on the whole source, the editor's red-eye view). Eye close-ups are
cut from the source and working images before geometry. The reported preview size is that of
the bounded `after` image.

Saved copies use the output width and height for the EXIF and XMP dimension fields and swap
the horizontal and vertical resolution on an odd number of turns. Orientation stays 1 because
the pixels are upright; thumbnails are still dropped and no crop tags are written.

## Limits

Peak memory is the read-only source, one eye-corrected buffer and one crop-sized buffer, at
most three times the source RGB bytes. Cancellation is checked before geometry, between tone
tiles and before publication. Synthetic tests show the arithmetic, not photographic quality.
