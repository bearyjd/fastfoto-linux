# Photo geometry (straighten, crop and quarter turns)

The photo editor can straighten by a small angle, crop to a free rectangle and turn the picture
in quarter turns. Crop and turns are exact pixel operations; only a non-zero straighten angle
resamples (see Interpolation). There are no aspect presets.

## Order of operations

Red-eye correction runs first, in source coordinates on the full retained original. The
straighten warp comes next, then the crop is cut from that result, the cropped pixels are turned clockwise, and tone is applied
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
- A slider drag is one undo entry; each keyboard step on the slider or angle box is its own.

## Preview and saved metadata

The preview publishes `before` (source), `after` (the bounded result with geometry) and
`working` (eyes plus tone on the whole source, the editor's red-eye view). Eye close-ups are
cut from the source and working images before geometry. The reported preview size is that of
the bounded `after` image.

Saved copies use the output width and height for the EXIF and XMP dimension fields and swap
the horizontal and vertical resolution on an odd number of turns. Orientation stays 1 because
the pixels are upright; thumbnails are still dropped and no crop tags are written.

## Straighten (schema 4, `photo-geometry-v2`)

The angle is an integer count of tenths of a degree in -150..150 (so +-15.0 degrees in 0.1
steps); positive tenths rotate the content clockwise as displayed. The output is the largest
axis-aligned rectangle inscribed in the rotated picture, so there are no empty corners and no
fill colour. That straightened frame F has size `frame_size`; the crop is measured inside F and
a full-F crop is stored as `null`. At angle 0, F is the source and v3 semantics are unchanged.

- Schema 4 stores `geometry` as exactly `crop`, `quarter_turns` and `straighten_tenths`. Only a
  non-zero angle moves a draft to schema 4, so edits without an angle stay readable by the
  previous release. Schema 4 never downgrades, and `photo-geometry-v2` is new because
  interpolation is new.
- An angle needs square pixels (equal horizontal and vertical DPI) and must leave F at least
  as large as the 5 mm minimum measured on the unrotated source.
- Eyes are still placed on the source; one outside F is simply not visible.

## Interpolation

Sampling is fixed-point bilinear at 1/32 pixel with 15-bit weights and a 24-bit trig table, so
it is integer-exact and identical on every machine. The warp is one fused pass into the final
layout (crop and quarter turn included) in 512 by 512 tiles, with cancellation checked per tile.
`cv2.remap` is used as an accelerator only: tests prove it bit-identical to the numpy reference
in the test tree (several sizes, angles and tiles) and the comparison is never loosened.

## Preview

An angled draft adds a `straightened` image (tone applied before the warp, a display aid) after
the other blobs. Benchmark on one thread (synthetic noise, this development machine, 2026-10-20):
8.6 MP preview at 2.3 degrees with tone 1.2 s (render alone 0.4 s); 89 MP render at 15 degrees
with crop and one quarter turn 2.1 s, tracemalloc peak 436 MiB beyond the held source.

## Limits

Peak memory is the read-only source, one eye-corrected buffer and one crop-sized buffer, at
most three times the source RGB bytes. Cancellation is checked before geometry, between warp and tone
tiles and before publication. Synthetic tests show the arithmetic, not photographic quality.
