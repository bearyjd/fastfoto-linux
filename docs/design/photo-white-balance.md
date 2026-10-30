# Photo white balance and tint

Backend and recipe only; the editor sliders and presets follow in a later change. Two integer
controls, `temperature` and `tint`, each -100 to 100 with neutral 0. Positive temperature is
warmer (more red, less blue); positive tint is magenta (less green), negative is green.

## Order of operations

Rendering replays from the retained source: eyes, denoise, straighten, crop, quarter turns, white balance, tone, sharpen
(detail sits at both ends, see [photo detail](photo-detail.md)).
White balance is per pixel, so it sits after geometry like tone. It writes uint8, and tone reads
that: the intermediate quantization is accepted. Adjustment strength does not blend white balance.
A neutral balance (0, 0) is a hard bypass: no table is built and no pixel is read, so the output is
byte-identical to a render without the feature.

## Math

Gains act per channel on linear light (sRGB transfer), a von Kries scaling. With `t` temperature
and `m` tint:

```text
decode(x) = x/12.92                     if x <= 0.04045 else ((x + 0.055)/1.055) ** 2.4
encode(y) = 12.92*y                     if y <= 0.0031308 else 1.055 * y ** (1/2.4) - 0.055
eR = t/200 ; eG = -m/200 ; eB = -t/200
g  = (2**eR, 2**eG, 2**eB)
k  = 0.2126*g[0] + 0.7152*g[1] + 0.0722*g[2]
gain_c = g[c] / k
lut_c[i] = floor(255 * encode(min(1, gain_c * decode(i/255))) + 0.5)   for i in 0..255
```

Dividing by `k` keeps the linear luminance of neutral grey. Spot values (4 dp): (100, 0) gives
(1.3255, 0.9373, 0.6628); (0, 100) gives (1.2650, 0.8945, 1.2650); (25, 0) gives (1.0762, 0.9869,
0.9050). Each channel is one 256-entry table applied in tiles, with cancellation between tiles.

## Recipe: schema 5 (`photo-color-v1`)

Schema 5 adds a top-level `white_balance` object with exactly `temperature` and `tint`; it is
present if and only if the schema is 5 or later, and schema 5 also keeps `straighten_tenths`. Values
must be plain integers: booleans, floats, `NaN`, infinities and strings are rejected. Only a
non-neutral balance upgrades a draft to schema 5; a draft never downgrades, so a schema 5 draft
returned to neutral stays schema 5. New drafts stay on schema 2. Older app versions reject schema 5
recipes; the saved JPEG stays a normal image. Saved files are never rewritten in place.

## Editor controls and presets

The editor shows **Temperature** and **Tint** sliders (-100 to 100, step 1) above the tone sliders,
in render order. A slider drag is one undo step. Four presets set absolute values for white balance
and tone (strength 100) in one undo step: Warm (25, 0), Cool (-25, 0), Faded print (temperature -10,
tint -10, contrast 15, saturation 25) and Black and white (contrast 10, saturation -100). They are
editor-only and are not stored in the recipe; the highlighted preset is derived from equal values.
Faded print counters the red and magenta drift of aged colour prints. The preset values are starting
points from synthetic reasoning, not calibrated on scans. **Reset adjustments** also neutralizes
white balance, in one undo step; the page Reset still restores the opened recipe.

## Limits

- The source is treated as sRGB-encoded; embedded profiles are not converted, so linearization is
  approximate for other profiles.
- Any gain above 1 clips highlights in that channel (a white border turns warm-white at positive
  temperature). There is no highlight protection.
- The gain scale (+-100 is a factor of 2 between red and blue) is an uncalibrated default.
- Evidence is synthetic: the tests check arithmetic and compatibility, not photographic quality.
- Not in scope: automatic or eyedropper balance, Kelvin units, masked balance, command-line flags,
  storing the chosen preset.
