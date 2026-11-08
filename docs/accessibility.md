# Accessibility

What the window does for keyboard and screen-reader users, what is checked automatically, and
what only a person can check (the Orca script at the end).

## What is checked by the tests

| Check | Test | What it pins |
| --- | --- | --- |
| Every named control has an accessible name | `tests/gui/qt/test_qml_accessibility.py` | The accessibility tree Qt builds (the one Orca reads) is walked on the scan page, the scanner settings page, the document page review and the photo editor. Any control with an `objectName` and an operable or status role (button, check box, combo box, text field, slider, spin box, tab, list, progress bar, busy indicator, message) must have a non-empty name. Controls that exist only in some states (the banners, the busy indicator, the language download progress bar) are included even while hidden. |
| A disabled Scan button says why | same | Its accessible description is the same sentence the window shows beside it. |
| The scanner chip says the state in words | same | Its description is the scanner message. |
| The selected page in the review is "selected" | same | `Accessible.selected` follows the current page, so the selection is not only a border colour. |
| Eye markers say accepted or rejected with a symbol | same | A check mark or a cross sits on each marker next to its colour. |
| Tab order | same | The photo form is visited in reading order (mode tabs, folder, album, date, notes, loaded, backs, resolution, file size, options, enhanced switch, photo grid, scanner chip, Check again); the review visits the page grid then Back then Save; every visible, enabled control with an object name on the scan page is on the Tab chain. |
| Text contrast | `tests/gui/test_accessibility_contrast.py` | See below. |
| Keyboard position in the lists | same | The photo grid and the document list draw a 2 px outline in the text colour around the current item while they have focus (before, it was only a faint tint). The selected page in the review has a 2 px text-colour border. |

The tests are structural: they prove names, roles, states, descriptions and the Tab chain, not
how a screen reader pronounces them. That is what the manual script below is for.

## Contrast

The window takes its colours from the Kirigami theme, so they follow the user's colour scheme.
The test pins two real schemes (the values in KDE's `BreezeLight.colors` and
`BreezeDark.colors`, `[Colors:Window]` and `[Colors:View]`), reads every text colour the QML
uses from the `.qml` files, and computes the WCAG 2.x ratio on the four backgrounds the text
can sit on (window, window alternate, view, view alternate). Text must reach 4.5 to 1.

Found and fixed (colour changes only, no layout):

| Text | Raw theme colour (Breeze Light, worst of the four backgrounds) | Now |
| --- | --- | --- |
| Hints and secondary text (about 20 labels) | `disabledTextColor` 3.3 | the text colour at 75 % opacity, 5.9 |
| Error text | `negativeTextColor` 3.4 | the error colour with 30 % text colour mixed in, 5.1 |
| Warning text | `neutralTextColor` 2.2 | the warning colour with 60 % text colour mixed in, 6.3 |
| "Not processed" badge text | `negativeTextColor` on `negativeBackgroundColor` 3.2 in the Kirigami palette of a test run (not pinned, see below) | the plain text colour |

Breeze Dark passes with the raw colours except error text (3.3 to 4.3), which the blend lifts
to 5.0 and above.

Not covered by a computed ratio, and why:

- The eye markers and the crop rectangle are drawn over the photo, so their contrast depends on
  the picture. They keep a fixed colour plus a symbol (markers) or a white outline.
- The focus ring of buttons, fields and check boxes is drawn by the Qt style. In Breeze Light
  the focus colour is 2.0 to 2.5 to 1 against the window, below the 3 to 1 of WCAG 1.4.11.
  This is the system style, not something the app can change here.
- `negativeBackgroundColor` (the badge fill) is derived by KDE at run time from the scheme, so
  it is not pinned.
- Disabled controls (half opacity) are exempt under WCAG 1.4.3.
- Schemes other than the two pinned ones are not checked. A very low-contrast scheme can still
  make secondary text hard to read, because the blends scale with the scheme's own text contrast.

## No information by colour alone

- Page state in the review: "Keep", "Removed", the flag text and "Cropped" are words; the border
  colour only repeats the selection, which is also exposed as `selected`.
- Photo cells: "Not processed" and the reason are text.
- Eye markers: a check mark (accepted) or a cross (rejected) next to the colour, and the editor
  says "Accepted" or "Rejected" in words for the selected eye.
- Scanner state: the chip text says "Scanner found" or "No scanner" beside its icon.
- Errors and warnings: always a sentence; the colour is extra.

## Keyboard map

| Where | Keys |
| --- | --- |
| Everywhere | Tab and Shift+Tab move between controls; Space or Enter presses a button; arrows change a combo box, slider or spin box. |
| Photo grid and document list | Tab to enter, arrows to move; the current item is outlined. |
| Document page review | Arrows move; Space or Delete keeps or removes a page; R rotates (Shift+R the other way); S splits the document here; Ctrl+Left or Ctrl+Right moves a page; Enter opens the preview. |
| Photo editor image | Tab to focus; + and - zoom; arrows pan; 0 fits. |
| Crop in the page preview | Tab to the crop area; arrows move the rectangle, Shift+arrows resize it; Enter applies, Escape cancels. |

## Checklist for a new control

1. It has an `Accessible.name` (the visible text, or a short phrase if it has an icon only).
2. If the reason it is disabled or its effect is not obvious, it has an `Accessible.description`.
3. If it is not a standard control, it has an `Accessible.role`; a list item that can be selected
   sets `Accessible.selected`.
4. It can be reached with Tab, in reading order, and shows where the focus is.
5. Text colours are `Kirigami.Theme.textColor` or one of the blends in the QML (the contrast
   test rejects a raw `disabledTextColor`, `negativeTextColor` or `neutralTextColor` as a text
   colour).
6. Anything said by colour is also said by a word or a symbol.
7. Add its `objectName` so the name sweep covers it.

## Manual test with Orca

This needs a person with a desktop session. Orca is the GNOME screen reader and also works on
KDE. Allow 20 minutes. Use a scanner-less run (the window works without one) except where noted.

Setup:

1. Install Orca (`sudo dnf install orca`), turn it on with Super+Alt+S (or run `orca`).
2. Make sure accessibility is on: in KDE System Settings, Accessibility, Screen Reader; in GNOME,
   Settings, Accessibility, Screen Reader. Log out and in if you just turned it on.
3. Start the app. Orca should say the window title.

Run through these and note any step where Orca says nothing, says "unlabeled", says a wrong
name, or where the keyboard focus is not visible:

1. Scan page, photos. Press Tab repeatedly. Expect, in order: Photos tab, Documents tab, Save
   photos in, Choose, Album, Date, Notes, Loaded, Keep backs, Resolution, File size, the four
   check boxes, Show enhanced copies, the photo list, the scanner chip, Check again. Each should
   be announced with its label and role (edit, button, combo box, check box).
2. With no scanner connected the Scan button is disabled, so Tab skips it. Use Orca's flat
   review (Orca+Numpad 7 and Numpad 4 or 6, or the laptop layout equivalent) to reach Scan: it
   should be announced as unavailable, and its description should be the sentence the window
   shows beside it ("Press Check again to look for the scanner." before the first check).
3. Choose the Documents tab with Space. The form changes; Tab through it. "Searchable text"
   should be a check box; "Languages" a button; the language list check boxes should read
   "English (eng). Installed" style names.
4. Press Check again. Orca should announce the progress text or the error. The error banner
   should be reachable with Orca's flat review and be called "Error" followed by the message.
5. Open scanner settings from the header (Scanner settings button). Tab through the power
   timer controls; each combo box and button should have a name. Press Back.
6. With a scanner (a hardware step; the tester decides): run a document scan that opens the
   page review. In the page review, Tab to the page list, press Down; Orca
   should say "Page 2, kept" and, after Space, "Page 2, removed"; check it also says
   "selected". Press R to rotate and S to split; confirm the cell text changes.
7. Tab to Save and press Enter. Orca should announce the result banner.
8. Photo editor (needs a processed photo): from a photo cell press Tab to "Edit photo" and
   Enter. Tab through Compare before and after, the geometry, colour and detail controls (each slider should name the adjustment and
   say its value), the eye list, Accept, Reject. Orca should say "Accepted" or "Rejected" in
   words when you change the status. Focus the image (Tab) and press + and -.

Also check, with no screen reader, using only the keyboard:

- You can scan, review, save and open the saved file without the mouse.
- The focus outline is visible on every control you land on, in both a light and a dark colour
  scheme (try Breeze Light and Breeze Dark in System Settings, Colours).
- With the system font enlarged to 150 %, secondary text is still readable and nothing is cut
  off.

Report findings as a list of step number, what Orca said, what it should have said.
