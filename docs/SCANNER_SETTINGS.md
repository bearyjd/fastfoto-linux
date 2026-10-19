# Scanner power settings

The desktop app can read and change the FF-680W's sleep and AC power-off timers
through USB. Open **Scanner settings** from the scan page. Opening the page makes
no scanner connection and changes nothing.

## Read the scanner's settings

1. Connect the scanner by USB and switch it on. Close other scanning programs.
2. Open **Scanner settings**, then choose **Read settings** under **USB power settings**.
3. Read the current **Sleep delay** and **Power off delay (AC)**. After a successful
   read, **Refresh** reads those settings again from the same scanner.

A successful read binds the page to the scanner that answered. With more than one
USB scanner connected and no selected target, the read asks for an unambiguous
scanner; connect only the intended scanner before trying again. Selecting a
different scanner clears the old reading and draft.

The current value comes from the scanner. **Not read**, **Unavailable** and
**Unsupported** are different states; none means a zero-minute timer. The app does
not display a shipped driver template or a remembered preference as a current
scanner setting. An unavailable or unsupported timer cannot be edited.

## Change a timer

**Sleep delay** controls how long an idle scanner waits before entering sleep.
**Power off delay (AC)** controls when it switches off while idle on AC power.
An automatically powered-off scanner disappears from USB and needs its power
button to switch it on again. Sleep and power-off have separate timers.

1. Read the settings first.
2. Choose a supported delay. Values are in minutes. **Off** is offered only for a
   timer whose live capabilities allow zero; it disables that timer.
3. Choose **Apply changes** to send the edited values.

Changing a selection creates a draft. It does not write to the scanner. Only
**Apply changes** writes, and only edited timers are sent. Reverting an edit to its
current value leaves nothing to apply. Before writing, the app reads capabilities
and current values again and validates the requested values. It then checks the
scanner's parameter acknowledgement and obtains a fresh reading. Success is shown
only after the returned settings match the requested changes; the verified values
replace the draft.

Reading or applying shares the app's worker with scanning and review jobs.
Conflicting actions are unavailable while a job is running. Finish or cancel the
active job before using the settings page. Changing settings does not feed paper.

## When a setting cannot be read or verified

- **Scanner absent or busy:** check power and USB, and close the other scanning
  application. Use an explicit read after the conflict is resolved. Claiming USB
  does not override a scanner reservation by another computer.
- **Unsupported or unavailable timer:** the control remains disabled. The app does
  not replace a missing capability with the ranges in a model profile.
- **Rejected value or different readback:** read the message. A rejected operation
  or a different returned value is not a verified change. Use **Refresh** only
  when it is available, inspect the returned values, then decide on another edit.
- **Uncertain result or interrupted communication:** the app cannot establish
  whether the scanner accepted the change. It does not automatically retry or
  replay the write. Stale readings are cleared; do not assume the old or requested
  values are current.

Some communication failures can leave the scanner waiting for the rest of a
command. The page then says **Turn the scanner off and on before continuing.**
The app blocks device reads, applies, scanning and scanner checks for that USB
target until a new physical USB enumeration is observed. Close any other scanner
program, switch the scanner off and on, and wait for it to appear on USB again.
Use **Check USB reconnection**, which checks USB metadata without sending scanner
commands, then use **Read settings** again. Reopening the page, restarting the app
or retrying the same USB address does not clear the block. The recovery record is
saved before scanner communication so an interrupted app cannot silently discard it.
This record belongs to the current app installation and profile. If communication
was interrupted, switch the scanner off and on before using another scanning app,
another profile, or switching between native and Flatpak installations. Disconnecting and reconnecting USB alone is
not established as a scanner protocol reset; follow the restart instruction.
Processing existing image files remains available.

If the app reports that its saved recovery state is unreadable or corrupt, it
cannot identify the previous USB connection safely. A scanner restart alone cannot
clear that error. Close the app and switch the scanner off first. Use the path in
the error to repair access to that recovery record, or remove only the corrupt
record while the scanner remains off. Restart the app with the scanner still off,
then switch it on and read its settings again. Do not remove a healthy pending
recovery record to bypass the normal restart check.

## Scope and evidence

These controls use USB even if scans normally use Wi-Fi. Network timer configuration
is not provided. The app does not offer the vendor utility's other maintenance
functions, reset counters, provision Wi-Fi or configure physical-button actions.
No settings are written on page opening, value selection, refresh or reconnection
checks. There is no automatic write retry.

Epson documents these timers in the [FF-680W user's guide](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/home_space_topics/a_distributed/ff680w_home_space_topic.html).
The [Linux Epson Scan 2 manual](https://download.ebz.epson.net/man/linux/epsonscan2_e.html)
section 9.9.4 describes the timers and excludes network configuration of these
settings. [Scanner capabilities](SCANNER_CAPABILITIES.md) records model-specific
ranges, the vendor API inventory, software features and application gaps. Those
static ranges describe the inspected driver model, not this scanner's current
settings. Development verification uses simulated USB exchanges; attended hardware
acceptance is a separate check.
