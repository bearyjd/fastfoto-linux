# FF-680W capabilities and vendor interfaces

Research checked: 2026-10-18. Application comparison includes the USB power settings
panel. Other feature comparisons use the application at `c6a97f7`.

This inventory records available evidence and application coverage. Research used official
Epson manuals and statically inspected vendor source/model resources. No vendor
program was run, no scanner was opened, and no current settings were read. Model
templates are not live capability replies or factory-default guarantees.

## Reading the status columns

- **Supported**: the FF-680W manual or its ES0170 profile supplies model-specific evidence.
- **Conditional**: a generic manual/API documents it, but FF-680W support or the exact
  available levels still requires a live capability reply or additional model evidence.
- **Software**: a host application feature, not a persistent scanner setting.
- **Absent**: the FF-680W hardware/profile excludes the feature.
- Application **implemented**, **partial**, and **missing** describe application coverage.
  Implemented does not imply live hardware validation.

## Scanner hardware, acquisition and configuration

The [settings guide](SCANNER_SETTINGS.md) describes the implemented power panel.

Evidence codes: **F** = FF-680W user's guide; **M** = ES0170 model profile; **H** =
Windows ES0170 hardware value archive; **L** = generic Linux manual; **S** = shipped
Linux source. Exact sources and artifact hashes appear below.

| Feature family | FF-680W evidence and support | Application coverage |
|---|---|---|
| USB and Wi-Fi scanning | Supported, F/M: USB 3.0 and 802.11b/g/n; M `ESConnectionType=2` means both | Implemented: USB discovery/gap shim, explicit network target |
| IPv6 | Supported in M (`ESIPv6=1`); actual transport/address configuration conditional | Partial: network target exists; no dedicated IPv6 configuration UI verified |
| ADF simplex/one-pass duplex | Supported F/H; H `functionalUnitType=[2]`, `duplex=[0,1]` | Implemented: fronts or duplex |
| Colour, grey, black/white | Supported F; 24-bit RGB, 8-bit grey, 1-bit monochrome output | Implemented; document scans acquire colour then apply selected output conversion |
| Automatic colour classification | Conditional host processing; exposed by L/SDK, no FF-specific option proof here | Partial: document processing classifies output; no vendor Auto image-type control |
| Resolution | F: optical 600 dpi; FastFoto output 300/600/1200, ScanSmart 75–1200 subject to length. H acquisition x/y list is 300/600; M driver range 50–4800 is not optical-resolution proof | Partial: `ScanJob` accepts 50,75,100,150,200,240,300,360,400,600; document UI 200/300/600. No 1200 output |
| Scan size, custom area, units | Supported F/M/H: sheet-feed geometry; M minimum 50.8×50.8 mm | Partial: app caps length at 393.7 mm; no width/area/unit editor |
| Long documents and panoramic photos | Supported F/M; limits depend on software, dpi and width | Missing beyond 393.7 mm; retain F limits rather than generic 3000 mm claim |
| Carrier sheets and plastic cards | Supported F/M; `ESCarrierSheet=2` = automatic; `ESADFCard=3` = landscape | Missing dedicated modes/guidance in controls |
| Mixed photo/document sizes, folded/thick originals | Supported with the loading restrictions in F | Partial: processing handles different sizes; no explicit special-original presets |
| Automatic size, paper-end, cropping, overscan | Supported model resources M/H; host and device components vary | Partial: photo crop and conservative document trim; no general acquisition controls |
| Skew correction | Supported H `skewCorrection=[0,1]` | Implemented: SANE `--adf-skew`; software crop/trim also used |
| Double-feed detection | Supported F/M/H; H `doubleFeedDetection=[0,1,3]`, length detection `[0,1]`. Exact enum semantics must use source/runtime caps | Missing user controls; scan errors are reported |
| Detection area/length/paper thickness | Conditional L; H contains range offset/length placeholders, not validated usable values | Missing |
| Double-feed skip | Supported physical button F | Hardware action only; no app control |
| Double-feed stop timing | Conditional L/S; not in inspected FF-specific H values | Missing; do not show as supported from generic source alone |
| Slow feeding | Supported physical slow-mode button F; M quiet-mode flag is 0 | Hardware action only; do not equate slow feed with an adjustable quiet-mode API |
| Automatic feeding mode/timeout | H has timeout range 0–30 and current-template field; F identifies the indicator. Availability and timeout unit require verification | Missing |
| Scan/stop/power buttons and lights | Supported F; M interrupt flag 1 | Partial: app Cancel exists; physical scan-button launch integration missing |
| Scan-button default application | Supported F, configured in Epson host software | Missing; an OS/application association, not established as device flash configuration |
| Sleep timer | Supported M/H; H 1–240 minutes, step 1 | Implemented: USB read/edit/apply with live capabilities and readback |
| AC automatic power-off | Supported F/M/H; H 0,30,60,120,240,480,720 minutes; 0=Off established in S | Implemented: USB read/edit/apply; Off offered only when advertised |
| Network energy saving | M flag 1; exact behaviour/control and transport restrictions conditional | Missing; flag alone does not establish a user-facing toggle |
| Battery/second power-off timer | No FF-680W battery support established; generic token/SDK machinery insufficient | Do not expose |
| Power off if disconnected / direct power-on | Conditional L/S only; absent from inspected FF-specific H setting lists | Missing; require capability proof |
| Product/model, firmware, serial, connection/status | Supported F/M/H/S; H placeholders are not this user's identity or firmware | Partial: target/device discovery and readiness/error reporting; no information panel |
| Glass dirt detection/sensitivity | Supported M `ESGlassDirtyDetection=1`, `ESShowGlassDirtyDetectLevel=1`; H sensitivity `[0,1,2]` | Missing; software streak detection is a different feature |
| Paper protection sensitivity | Conditional L/S; no FF-specific profile/value support found | Missing; keep separate from skew correction/double-feed |
| Total simplex/duplex, special-document counts | H lists corresponding counters; runtime readability still needs confirmation | Missing |
| Jam, ultrasonic/length double-feed counts | H lists counters | Missing |
| Lamp counters | H lists feeder lamp 1/2 counters | Missing; expose only if useful and readable |
| Roller count/lifetime/reset | Supported F/M/H; M `ESRollerCount=1`; F explicitly documents reset after replacement | Missing; reset is a separate explicit maintenance action |
| Cleaning reminders/count/reset/threshold | M cleaning-alert template limit 5000; generic L/S document full workflow; H does not prove every operation | Missing; per-operation support conditional |
| Feed-position/drive/back-light adjustments | M `ESUtilAdjustment=1`; H has front/back top correction, front drive correction and back light intensity | Missing; maintenance/calibration scope requires dedicated design and live capability proof |
| Wi-Fi provisioning, WPS/PIN, disable/reset network | Supported manual workflows F; network security/IP setup also documented | Missing in app; existing network scanning expects configured scanner |
| Flatbed, film/TPU, battery and generic printer/MFP maintenance | Absent/not established: M flatbed/film/TPU flags 0; do not import other-model APIs | Out of scope for FF-680W |

Important acquisition limits from the FF-specific specifications: photo output up
to 8.5×36 inches at 300/600 dpi and 8.5×15.5 at 1200; document output up to
240 inches at 200 dpi, 214 at 300, and 15.5 at 600. Receipt rules differ by width.
The hardware template has its own longer-length table: do not replace documented
workflow limits with a single universal number. Interpolated output is not new
optical detail. [FF specifications](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/specifications/references/ff680w/spex_general_scanner_ff680w.html)

## Photo processing and library features

These are host-software capabilities documented specifically for FastFoto with
FF-680W. They do not belong in device-maintenance PARA writes.

| Documented feature | Application coverage |
|---|---|
| Output folder, batch subject/date, folders/naming | Implemented: folder, album/date, collision-safe numbering, metadata |
| Original/enhanced copy selection | Implemented: originals and `_a` copies; enhanced-only option |
| Auto brightness/contrast/saturation | Partial: restoration pipeline; no separate vendor-equivalent Auto Enhance control |
| Fade restoration; red-eye reduction | Implemented as independent local processing |
| Front/back pairing and writing-detection sensitivity | Partial: auto/always/never backs; no sensitivity slider |
| Photo type and output format choice | Missing dedicated photo-type presets/format selector; JPEG output |
| Auto rotation | Implemented: face-based orientation |
| Curled-photo edge-brightness correction | Missing |
| Line/streak reduction | Partial: document streak analysis exists; photo reduction parity not established |
| Preferred viewer / macOS Photos album integration | Missing |
| Usage/error reporting to Epson | Missing; host preference |
| Email sharing | Missing |
| Manual/automatic Dropbox or Google Drive upload | Missing |
| Post-scan rotate/crop/enhance/restore/red-eye/date/undo edits | Missing photo editor; document review has separate rotate/reorder/remove operations |

Sources: [FastFoto settings](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/scanning_software/reference/available_settings_fastfoto2_ff680w.html),
[edit menu](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/scanning_software/reference/editing_options_win_fastfoto.html),
[email](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/scanning_software/tasks/sharing_photos_win_fastfoto.html),
[uploads](https://files.support.epson.com/docid/cpd5/cpd55191/source/scanners/source/scanning_software/tasks/uploading_photos_win_fastfoto.html).

## Document application features

The FF-680W guide links the [ScanSmart guide](https://files.support.epson.com/docid/cpd5/cpd55726/helpcontents.html).
Its software inventory includes scan/review/save, email/cloud/print actions,
Office-format OCR exports, scanner/scan/name/save settings, action-icon editing,
and scan-application association. Invoice/Receipt Manager is separately activated
software: extraction/database management; QuickBooks Online/Desktop, Quicken,
TurboTax and CSV exports; category/column/currency/language preferences.
These are software capabilities, not universal FF-680W firmware features.

Application comparison: scan/review, blank detection, rotation/reordering/removal,
manual PDF splitting, naming, searchable PDF OCR and language management are
implemented. Office exports, print/email/cloud actions, receipt-accounting
extraction and those integrations are missing.

The [Linux manual](https://download.ebz.epson.net/man/linux/epsonscan2_e.html)
additionally catalogs generic host features: rotation, blank skipping, background
processing, dropout, text enhancement, brightness/contrast/gamma/threshold,
JPEG/PNM/PNG/TIFF/multipage TIFF/PDF output, file options/naming/folders, preview,
add/edit pages, remembered preferences and reset. Availability is model dependent.
App parity is partial: PDF/JPEG/PNG intermediates, local processing and review exist;
there is no complete vendor filter/output/preferences editor. Its documented CLI
families are `--scan/-s`, `--create/-c`, `--edit/-e`, `--list/-l`,
`--set-ip/-i`, `--help/-h` and `--get-status/-gs`. SDK sample timer switches are not established
as `epsonscan2` executable options. The manual says power-save settings cannot be
changed over a network.

## Public shipped SDK surface: complete function list

The source archive supplies `src/ScanSDK/Src/ESCANLIB.h` and a C++ sample. This is
stronger evidence than strings found in a binary, but is not a guarantee of a
supported ABI, every declared mode, installed availability, or FF-specific behaviour.
No standalone full SDK reference manual was found in this archive.

All nine exported C declarations in that header:

| Function | Contract family | FF-680W / application status |
|---|---|---|
| `eslInit` | Create SDK instance/key context | Generic lifecycle; not used by app |
| `eslFree` | Dispose instance | Generic lifecycle; not used |
| `eslOpenScanner` | Open `ConnectInfo`: local/IPv4/IPv6/default | FF model supports USB/network; runtime availability unverified; not used |
| `eslCloseScanner` | Close scanner | Generic lifecycle; not used |
| `eslCtrlParameter` | Set, get current, get default typed parameter block | Capability/model conditional; not used |
| `eslExecute` | Scan, store, save, retrieval/recognition modes | Declaration exceeds Linux implementation; see below; not used |
| `eslGetSettingParameter` | Read selected persistent timer | Only sleep and AC power-off selectors declared; FF model supports both; not used |
| `eslSetSettingParameter` | Set selected persistent timer | Same selectors; actual range/readback needed; not used |
| `eslGetDeviceStatus` | Return scanner status/error code | Linux declaration (`#ifndef WIN32`); not used |

`SP_SLEEP_TIMER=0` and `SP_POWER_OFF_TIME=1` are the entire public setting selector
enum. There is no public setting selector here for glass dirt, rollers, network
provisioning or paper protection.

All declared parameter families:

| Block(s) | Declared controls | Linux 6.7.80 implementation evidence |
|---|---|---|
| `EslParamScanBasic`, `EslParamScanExV1` | Source; colour; dpi; standard/custom size/unit/rectangle; rotation; brightness/contrast/threshold; colour dropout/enhance; page count. Ex adds document enhancement, filters, double-feed, blank skip, punch-hole and skew controls | ScanMgr dispatch accepts both. Each option remains model/processing dependent |
| `EslParamSaveBasic` | Page range, output format/path, name prefix/time/counter | Accepted |
| `EslParamSaveExV1` | Adds barcode/OCR names and detection regions; pagecount/blank/barcode/OCR separation; separator removal and subfolder naming | Declared; absent from ScanMgr parameter dispatch inspected here |
| `EslParamSaveJPEG` | Quality, progressive encoding | Accepted |
| `EslParamSaveTIFF` | Byte order, colour/grey/mono compression, quality | Accepted; inspected converter only maps mono None/CCITT G4, not all declared fields |
| `EslParamSavePDF` | Normal/PDF-A/high compression; searchable text/language | Declared; absent from inspected parameter dispatch |
| `EslParamOBRBasic` | Barcode page/region/symbology/orientation/count | Declared; no matching dispatch/execute implementation established |
| `EslParamOCRBasic`, `EslParamOCRExV1` | OCR page/region/language and character classes | Declared; no matching dispatch/execute implementation established |
| `EslParamInfoBasic` | Serial number and reserved fields | Get-current/default dispatch includes it; no setting support |

Header format enum: BMP, JPEG, TIFF, MultiTIFF, PDF, PNG, OFD. These names alone do
not establish working Linux support for every format. Barcode enums include
UPC/EAN/JAN, ITF, Code39, Codabar, Code128, QR, PDF417, Data Matrix. OCR enums include
OCR-A/B and EN/JA/ZH-TW/ZH-CN/KO/FR/IT/DE/ES/PT/NL/RU/UK. These describe declared
software interfaces, not scanner firmware OCR/barcode engines.

Execute/callback families: `ET_SCAN_AND_SAVE`, `ET_SCAN_AND_STORE`,
`ET_SAVE_STORED_IMAGE`, `ET_GET_STORED_IMAGE`, `ET_GET_OBR_DATA`, `ET_GET_OCR_DATA`;
scan-status, image-file, image-memory, barcode and OCR callback structures.
**Implementation limitation:** `ScanMgr.cpp:194` accepts the first four execute
types; OBR/OCR requests fall to invalid-parameter. At line 1115 `execSave` forces
`ET_SAVE_STORED_IMAGE`, so declared memory retrieval must not be presented as
verified working. Only scan-status/image-file callbacks are registered there.

Status families include ready, cover open, jam, empty, fatal/lamp/lock, double-feed,
tray closed, battery, carrier/edge/gap sensors, paper protection, separation lever,
pose and unknown. Generic status constants do not prove those sensors exist in
FF-680W. Error families also cover cancel, invalid state/parameter/key, missing
driver/files, I/O/disk/memory and unsupported operations.

`SCN_Get_Setting_Parameter`, `SCN_Set_Setting_Parameter`,
`SCN_Get_Device_Status` and the sample's `--get/--set-sleeptimer` and
`--get/--set-autopwoff` are **sample helper functions/options**, not additional
exported SDK APIs. The vendor sample/backend also contains C++ chained comparisons such as
`min <= value <= max`; do not copy that validation into application code.

## Source-visible lower-level controller API

`src/Include/Controller/EpsonScan2.h:477–524` exposes the following complete set
of 35 function declarations. Treat these as source-visible controller interfaces,
separate from the sample-facing SDK contract; no stable external API promise was
found. They are generic; actual keys/capabilities determine model applicability.

| Family | Function names |
|---|---|
| Discovery | `SDIDeviceFinder_Create`, `StartDiscovery`, `StopDiscovery`, `SetTimeout`, `GetDevices`, `Dispose`; `SDIDeviceInfo_Resolve` |
| Driver lifetime | `SDIScannerDriver_Create`, `Open`, `Reset`, `Close`, `Dispose` |
| Key/capability access | `SDIScannerDriver_GetAllKeys`, `SetValue`, `GetValue`, `GetDefault`, `GetCapability` |
| Cautions/admin lock | `SDIScannerDriver_CheckCautionStatus`, `UnlockAdministratorLock`, `LockAdministratorLock` |
| Scan/events | `SDIScannerDrive_DoScanJob` (header spells Drive), `SDIScannerDriver_CheckNextTransferEvent`, `GetNextTransferEvent` |
| Images | `SDIImage_Create`, `GetWidth`, `GetHeight`, `GetSamplesPerPixel`, `GetBitsPerSample`, `GetPath`, `CheckImageIsBlank`, `Dispose` |
| Output conversion | `SDIMultipage_Start`, `Add`, `Fin`; `SDIConvertJpegToFormat` |

Unprefixed names in each cell retain the first name's prefix. Function-pointer
typedefs sometimes differ from the declaration spelling and are not extra
functions (`SDIScannerDriver_DoScanJobPtr`, for example). The
`SDIDeviceFinder_FreeDevicesPtr` typedef has no corresponding function declaration
in the inspected block. No lower-level controller API is used by the app.

Private C++ methods, `ESUtil*` Windows strings, ESC/I-2 tokens and `GetValueForKey`
symbols are implementation evidence, not additional documented user features or
public SDK entry points. Relevant maintenance protocol families are capabilities,
results/current values, parameters and finalize; use actual device capabilities
before any write. The app implements its maintenance exchange independently; it
does not load the vendor SDK.

## Complete FF-680W hardware-value key coverage

For auditability, these groups cover every one of the 54 keys in the inspected
`ES0170_hw.db/ADF/AllAvailableValues.json`. A key's presence does not by itself
prove writability or a usable range; `no_data` entries need live capabilities.

| Group | Exact keys |
|---|---|
| Source/geometry | `functionalUnitType`, `scanArea`, `scanAreaInPixel`, `scanSize`, `scanSizeInPixel`, `xOffsetMargin`, `yOffsetMargin`, `xResolution`, `yResolution`, `pagesToBeScanned`, `duplex`, `skewCorrection`, `overScan`, `paperEndDetection`, `autoCropping`, `croppingSize`, `laminatedPaperMode` |
| Acquisition/session | `authenticationEnabled`, `interruptionEnabled`, `disableJobContinue`, `disableKeepingCapture`, `autoFeedingModeTimeout`, `workFolder`, `bufferSize` |
| Imaging | `imageFormat`, `colorFormat`, `colorMatrixMode`, `colorMatrix`, `gammaMode`, `gammaTableMono`, `gammaTableRed`, `gammaTableGreen`, `gammaTableBlue` |
| Double feed | `doubleFeedDetection`, `doubleFeedDetectionRangeLength`, `doubleFeedDetectionRangeOffset`, `lengthDoubleFeedDetection`, `lengthDoubleFeedDetectionLength` |
| Power/glass | `powerOffTime`, `powerSaveTime`, `sensorGlassDirtSensitivity` |
| Counters | `documentFeederLamp1Counter`, `documentFeederLamp2Counter`, `paperJamCounter`, `ultraSonicDoubleFeedCounter`, `lengthDoubleFeedCounter`, `rollerKitCounter`, `simplexScanCounter`, `duplexScanCounter`, `specialDocumentCounter` |
| Adjustments | `documentDriveCorrectionFront`, `documentTopCorrectionFront`, `documentTopCorrectionBack`, `lightIntensityBack` |

The shipped `AllCurrentValues.json` includes a synthetic `VirtualScanner` serial,
sample counts/date/error and template values. None are a reading of a connected
scanner. Additional read-only-looking keys there include firmware/version,
document-loaded/guide state, optical/max dimensions, sensor-glass status and roller
lifetime/near-end; live availability and read/write semantics are unverified.

## Provenance and licensing

1. [FF-680W guide contents](https://files.support.epson.com/docid/cpd5/cpd55191/helpcontents.html)
   and its topic pages above. Covers loading, controls, power, networking,
   FastFoto, maintenance, troubleshooting and specifications. Descriptive inventory
   only; do not redistribute manual text/screenshots without permission.
2. [Linux Epson Scan 2 manual](https://download.ebz.epson.net/man/linux/epsonscan2_e.html),
   last-modified text 2024-04-02, sections 8–10. Generic, explicitly model dependent.
3. [Official Linux 6.7.80.0-1 source](https://download3.ebz.epson.net/dsc/f/03/00/17/08/06/1babf9876ebb16956420a601b92ee28b57cd7db7/epsonscan2-6.7.80.0-1.src.tar.gz),
   2,538,110 bytes, SHA256
   `f8d617892e75fb43404824e627a4c5894f7e1283bb9840d7cdecfbcef24b2097`.
   All source paths above are relative to archive root `epsonscan2-6.7.80.0-1/`.
   Core headers identify LGPL-2.1+; `COPYING` and per-file notices govern reuse.
   `LICENSE` separately covers bundled MIT, Internet Society SHA and zlib code.
   The Linux manual distinguishes proprietary plug-in/binary licensing; source
   publication is not permission to redistribute all included binaries.
4. [Official Windows 6.7.71 driver](https://ftp.epson.com/drivers/FF680W_EScan2_67710_NA.exe),
   77,932,936 bytes, SHA256
   `5b197f422fed5cc17a34439eee373041d0497648f28056296bac3f8c04c1390c`.
   Static extraction chain `ES0170.cab` → `ES0170.db`/`ES0170_hw.db` (ZIP JSON).
   `ES0170.db`: 1900 bytes, SHA256
   `ffa87fc72369660cc1687cea8ed359a30a486e123ec4c0edc018478f1fff43e4`.
   `ES0170_hw.db`: 4356 bytes, SHA256
   `cde8f152662e367212587b5a57ce99b2f68ea9c532f8cdc70c67299a6b1a07dd`.
   Vendor Windows artifacts remain proprietary; this inventory records facts and
   references, not distributable DLLs/databases.
5. Application evidence: README sections Developer CLI, Documents to PDF and Desktop app;
   `src/fastfoto_linux/scanner/job.py:12`, `:41`, `:79`;
   GUI form/docform/prefs and enhancement/document modules. Baseline uses SANE,
   libusb readiness and local processing, not the vendor SDK.

## Scope limits

This inventories the functions documented by the FF-680W/FastFoto guide, the linked
ScanSmart guide's user-feature families, the generic Linux manual, all exported
sample-facing SDK declarations and the source-visible controller function families.
It does not promise every undocumented Windows utility command, firmware feature,
regional software edition, paid add-on or future SDK. Conditional rows require
additional evidence, not automatic implementation.

The implemented panel covers USB sleep and AC power-off timers. It reads live
capabilities/current values, applies only requested changes and verifies readback.
Scanner information, counters, glass-dirt controls, counter resets, calibration and
network provisioning remain separate features. Conditional rows need more evidence
before implementation. Static profiles supply expectations, never current values.
