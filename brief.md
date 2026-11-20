# Project: driving a Sony NEX-5R from N.I.N.A. (ASCOM Alpaca)

## Goal

Control a Sony NEX-5R from N.I.N.A. for astrophotography: take exposures, download the images, and run N.I.N.A.'s autofocus by driving the focus of a **focus-by-wire E-mount lens** mounted on the camera. Use at the focus of a telescope may come later.

## Hardware and environment

- Camera: Sony NEX-5R (APS-C, 16.1 MP, 2012), firmware 1.03, PlayMemories Camera Apps (PMCA) compatible, built-in Wi-Fi.
- Lens: Sigma 30mm DC DN (E-mount, electronic focus). `pmca-console info` reports it as "Model 0xa0c530", firmware 3.01.
- Development machine: Mac (Apple Silicon). The Alpaca Server also runs on it during development.
- Astro machine: a Windows mini-PC running N.I.N.A. (Windows only) and, in the field, the Alpaca Server.
- Power: the NEX-5R does not charge over USB. Use the AC-PW20 adapter (or a dummy battery) for a whole night.

## Why an app on the camera

- **No USB control.** The NEX-5R does not support USB tethering: with the cable plugged in, it switches to file transfer. The reference Sony ASCOM driver (dougforpres/ASCOMSonyCameraDriver) is USB only, so it cannot be used.
- **The official Wi-Fi API** (Sony Camera Remote API, "Smart Remote Control" app) was ruled out: JPEG only, uncertain Bulb support, no usable step-by-step focus.
- **Chosen approach:** a custom Android app on the camera. Sony-PMCA-RE (ma1co) installs custom apps on PMCA cameras. Apps must run on Android 2.3.7, debug certificates are accepted, and Sony's internal APIs are reachable through OpenMemories: Framework.

## Architecture

```
[NEX-5R]                         [Alpaca Server]                    [Windows PC]
camera-app        <-- Wi-Fi/HTTP -->  Python (Mac or PC)  <-- Alpaca -->  N.I.N.A.
 - focus offsets                       - Camera device
 - Bulb exposure, ISO                  - Focuser device
 - serves the ARW files                - ARW -> Bayer ImageArray
```

- `camera-app/`: the app on the camera. Build, install and debug: `camera-app/README.md`.
- `alpaca-server/`: the Alpaca Server, based on ASCOM's AlpycaDevice template. Behaviour, configuration and N.I.N.A. settings: `alpaca-server/README.md`.
- Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/`.

## What the camera can do (established)

### Focus

- `CameraEx.startOneShotFocusDrive` is **absent** from the NEX-5R firmware. `CameraEx.shiftFocusPosition(int)` exists (Sony's Bracket Pro uses it) and drives the Sigma 30mm, camera at rest (`focus-shift-supported=true`).
- **The argument is an absolute offset** from a reference point, limited to −16..+16, not a relative move. Each call returns `true` in 230-300 ms. It must be called from a thread other than the UI thread, or it never returns.
- **Without any autofocus since the app started, the call blocks forever and freezes the camera** (restart required). An autofocus run once, the **Arming**, sets the reference point. It can run in `manual`: then the lens does not move, so the reference is the focus set by hand. The offsets move the lens only in `auto` or `dmf` mode (in `manual` they return `true` but do nothing). Changing the focus mode does not move the reference.
- A failed autofocus (uniform target) leaves the lens about where it was, and the offsets still work.
- The ±16 window is small: steps are fine, suited to refining around a rough focus. At 1-3 m, ±8 positions already divide sharpness by 10. Returning to the same offset is repeatable (sharpness within ±15 %), and exposures do not move the reference.
- Night procedure: rough focus by hand, Arming in `manual`, then switch to `auto`.

### Exposure

- **Long exposures are possible.** In M mode, `decrementShutterSpeed()` past 30" gives `getShutterSpeed() = 65535/1` = Bulb. `takePicture()` opens the shutter, and `cancelTakePicture()` N seconds later closes it. The EXIF matches the duration, and one ARW + JPEG per exposure appears on the card about 3 s after closing.
- **A software-triggered exposure only fires after broadcasting `APO/NO`.** The intent `com.android.server.DAConnectionManagerService.apo` with `apo_info = "APO/NO"` disables auto power-off. Without it, the shot stays pending and no file is written. Broadcast `APO/NORMAL` again when exiting.
- There is no end-of-capture callback (`OnCaptureStatusListener` and the like are missing from the firmware): watch for the file in DCIM. There is no long-exposure noise reduction setting either.
- The camera clock is in 1970: file dates cannot date the exposures.

### Network

- camera-app turns Wi-Fi on itself, and the camera joins its known network without OpenMemories: Tweak.
- camera-app serves DCIM over HTTP (port 8080). An ARW (16.3 MB) takes about 13 s, roughly 1.2 MB/s.

### With N.I.N.A.

- Daytime contrast-detection autofocus works end to end (N.I.N.A. 3.3 nightly, 2026-11-20): about 30 s per point, 5 min for 9 points. The pitfalls are listed in `alpaca-server/README.md`.

## Open questions

- Does Wi-Fi stay stable for a whole night?
- Night autofocus on stars (star HFR): not tested yet. How much blur does one step cause at infinity, and what step size does it call for?
- Does touching the focus ring after Arming (in `dmf`) move the reference point?

## Next

The Alpaca Server is about to get a Windows installer, a Dashboard, self-Update and CI with releases. The plan is in the GitHub issues, and the decisions are in `docs/adr/`.

## Links

- Sony-PMCA-RE: https://github.com/ma1co/Sony-PMCA-RE
- OpenMemories: Framework: https://github.com/ma1co/OpenMemories-Framework
- PMCADemo: https://github.com/ma1co/PMCADemo
- OpenMemories: Tweak: https://github.com/ma1co/OpenMemories-Tweak
- App list: https://github.com/ma1co/OpenMemories-AppList
- TimeLapse (its trigger sequence led to the `APO/NO` fix): https://github.com/jonasjuffinger/TimeLapse
- Compatible cameras: https://openmemories.readthedocs.io/devices.html
- Sony USB ASCOM driver (not compatible, for reference): https://github.com/dougforpres/ASCOMSonyCameraDriver

## Disclaimer

Unofficial, reverse-engineered hack. The risk is low for a simple app, but not zero: no warranty, either from Sony or from the authors of this project.
