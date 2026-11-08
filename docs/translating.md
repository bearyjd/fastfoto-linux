# Translating the desktop app

This is the groundwork for translations, not a finished feature. The desktop app can show its
text in another language, and one pilot language exists: **German (`de`), which is partial.**
Only a few dozen messages are translated; every other text stays English. The German strings were
written by the developer, have **not** been reviewed by a native speaker (a native-speaker review
is still needed, for example of `Neu prüfen` for the button and `Abbruch läuft …`), and are not
machine-translated or complete. Nothing here is a claim that the app is available in German. The
pilot proves the pipeline (extraction, compiling, loading, layout at the narrowest window), and
the translators are recruited only after 1.0.

The **interface language** is not the OCR language. OCR languages (`deu`, `eng`, ...) are
Tesseract models chosen in the Documents form (`DocumentForm.langs`); the interface language is a
separate setting and changing one does not change the other.

## For users

Open Scanner settings (the gear in the scan page) and choose **Interface language**. English is
the default and the app never follows the system language by itself, so English text and the
tests that pin it do not depend on the locale. German is listed as `Deutsch (partial)`. The choice
is saved in `gui.json` (key `ui_language`, values `en` or `de`) and applies from the next start;
the page says so.

## How it works

- QML text is written `qsTr("...")`. The context of a QML message is the name of its file.
- Text written in Python that reaches the window is marked with
  `QT_TRANSLATE_NOOP("messages", "...")` (`gui/i18n.py`; it returns the text unchanged, so the
  plain-Python modules and `ffscan` need no Qt). The text is looked up where it reaches QML, in
  the `Bridge` properties `scannerText`, `progressText`, `whyNotScan` and `errors`, through
  `gui/qt/translation.py:translate_message`. A text with no translation comes back as it is.
- Not yet marked: any message built with an f-string (it has numbers, names or paths in it),
  banners and the document report. Translating those needs `%1` style templates; that is
  follow-up work, not part of this pilot.
- The catalogs are in `src/fastfoto_linux/gui/translations/`: `fastfoto_<code>.ts` (the source
  translators edit) and `fastfoto_<code>.qm` (compiled, committed, shipped in the wheel).

## Translator workflow

You need Qt's `lupdate` and `lrelease` (Fedora: `sudo dnf install qt6-linguist`).

1. `tools/i18n.sh update` finds the messages in the QML and Python and merges them into
   `fastfoto_<code>.ts`. Run it whenever a user-visible string changes, and commit the result.
2. Edit the `.ts` file in Qt Linguist (`linguist-qt6`) or a text editor. A finished message has a
   `<translation>` with no `type` attribute; one still to do has `type="unfinished"`. Leave the
   rest unfinished: do not fill a message in with a guess.
3. `tools/i18n.sh release` compiles every `.ts` into its `.qm` (finished messages only, so an
   unfinished one falls back to English) and writes the SHA-256 of the `.qm` to
   `fastfoto_<code>.qm.sha256`. Commit the three files.
4. `tools/i18n.sh check` is what CI runs: it updates a temporary copy of each `.ts` and fails if
   the committed one differs, or if the committed `.qm` is not what `lrelease` makes of it.

Rules for a translation (enforced by `tests/gui/test_i18n.py`):

- Keep the same `%1`, `%2` placeholders as the English text.
- No `<`, `>` or `&` characters and no control characters: the text is shown as plain text.
- A text that ends in a full stop or an ellipsis keeps it.
- A message of the `messages` context is no longer than the English text plus 4 characters: those
  sit in the bar under the scan form, and a longer one wraps, makes the bar taller and squeezes
  the form above it. German is also tested at the narrowest window (`tests/gui/qt/test_ui_language.py`):
  no control of the form may move.
- Keep the wording of buttons and the messages that name them in step (the hint that says
  "Press Check again" must use the same words as the button).

To add a language, add its code and name to `UI_LANGUAGES` in `gui/i18n.py` (mark it
`partial=True` until every message is translated and reviewed), add the code to `languages` in
`tools/i18n.sh`, run `tools/i18n.sh update` and `release`, and add the same checks as for `de`.

## Trust model and safety of the translation files

Translation files are data read at run time. What is and is not guaranteed:

**The compiled catalog is trusted because of where it comes from, not because the app reads it.**
It is the file packaged with the app; its SHA-256 is pinned in `fastfoto_<code>.qm.sha256`
(a required test fails when they differ); it is byte-identical to a fresh
`lrelease -nounfinished` of the reviewed `.ts` wherever `lrelease` runs (see below); and the
loader checks its layout. The loader does **not** validate what the messages say: Qt reads
them, and a partial reader of the format in Python would be a false boundary.

- The app loads only `fastfoto_<code>.qm` for an allowlisted code (`en` or `de`) from the folder
  inside the installed package. Never the working directory, a settings value, an environment
  variable or another user-writable folder.
- The folder is opened from `/` one path component at a time, each step relative to the
  descriptor before it and refusing links, and the file is opened the same way and checked on
  the open descriptor (a regular file, at most 1 MiB). The bytes read are the bytes loaded, so
  nothing can be swapped for a link between a check and the open.
- Before Qt sees the bytes, `gui/qmformat.py` walks the section layout and refuses a catalog with
  a *dependencies* section (Qt follows an absolute path named there), an empty, unknown, repeated
  or out-of-order section (Qt stops reading at an empty one), a context table (a two-byte one
  makes Qt divide by zero), or a hash table that is not a whole number of records.
- Anything else wrong (missing, too big, refused, an exception, Qt cannot load it) leaves the
  interface in English and logs a warning without paths; it never stops the app. The window shows
  the language that really loaded, not the one saved: if the saved German cannot load, it shows
  English and no restart note.
- The rules for the text of a translation are checked on the reviewed `.ts` file, in
  `tests/gui/test_i18n.py`, for every plural form of a finished message: no `<`, `>`, `&` or
  control character, the same placeholders as the source (`%1` to `%9`, `%n`, `%Ln`), not blank,
  and a sentence end kept.
- The app's Python code never uses a translation as a format string: `translate_message` returns
  it as it is. QML does fill placeholders: `qsTr("... %1 ...").arg(value)` puts a value into the
  translated text, so the placeholders of a translation must match its source (tested). The
  new QML labels use `Text.PlainText`; Qt's own buttons and chips cannot be told to ignore
  markup, which is why the `.ts` rule against `<`, `>` and `&` matters.

**Rule for contributors and reviewers:** never accept a change to a `.qm` without the matching
change to its `.ts` and a passing recompare (`tools/i18n.sh check`, or the `lrelease` test below).

## Checks in CI

`tools/i18n.sh check` runs in the `translations (informational)` job. It is **not** a required
check; its step and the job have `continue-on-error`, so the job is always green: several
branches change QML at the same time and `lupdate` output can differ a little between Qt
versions, so a hard failure would stop unrelated pull requests. A stale `.ts` shows up as a
warning annotation. The script always recompiles the `.ts` and compares the bytes with the
committed `.qm`, whatever the Qt version; with a different Qt it can report a difference that the
version causes (the committed file was made with Qt 6.10.3).

Why the `.qm` is committed: a build hook that compiles it at wheel time would need `lrelease` in
every wheel build and in the Ubuntu jobs, which have no Qt. The required test jobs (which need no
Qt tools) check that the SHA-256 of the file equals the pin, that its layout is sound, that the
`.ts` rules above hold, and that every Label and Heading in the QML shows plain text. The test
that `lrelease` reproduces the exact bytes (`tests/gui/test_i18n.py`) runs only where `lrelease`
exists **and** is Qt 6.10.3, so it is not enforced by the required jobs; elsewhere it is skipped.
