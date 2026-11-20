# alpaca-server

ASCOM Alpaca server for the Sony NEX-5R: exposes the camera to N.I.N.A. (or any Alpaca client) as a `Camera` device (ICameraV4) and its focus-by-wire lens as a `Focuser` device (IFocuserV4). It talks to `camera-app`, the app running on the camera, over Wi-Fi.

Based on the official ASCOM [AlpycaDevice](https://github.com/ASCOMInitiative/AlpycaDevice) template (MIT, see `LICENSE-AlpycaDevice.txt`). `app.py`, `config.py`, `discovery.py`, `exceptions.py`, `log.py`, `management.py`, `setup.py` and `shr.py` come from it, with small changes marked `nex5r-ascom`:
- a threaded WSGI server;
- the Camera and Focuser devices instead of the Rotator;
- a routing filter.

## Files

- `camera.py`: Alpaca responders. ImageBytes when the client accepts it, JSON otherwise.
- `cameradevice.py`: one exposure at a time on a worker thread: Bulb, ISO, `/capture`, wait for the ARW, download, rawpy decoding.
- `focuser.py`: Alpaca Focuser responders.
- `focuserdevice.py`: positions, arming, one move at a time on a worker thread.
- `responders.py`: the responder factories both devices share.
- `nex5r.py`: HTTP client for camera-app (`/status`, `/shutter`, `/iso`, `/capture?ms=`, `/files`, `/dcim/`, `/focus`, `/focusarm`).
- `version.py`: the Version (ADR 0001), written by release-please. Both Devices return it as `DriverVersion`, the management description as `Version`, and the startup log line names it.
- `dashboard.py`, `dashboard.html`: the Dashboard (see Dashboard).
- `config-template.toml`: the template of the configuration (see Configuration).
- `tests/`: the test bench (see Tests).

## Dashboard

Open `http://<server address>:11111/` from any machine on the local network (with the default `ip_address = ''` the server listens on every address). The read-only page shows whether camera-app is Reachable and its Version, whether the Camera is Connected and exposing, whether the Focuser is Connected and armed and its position (0..32), and the Alpaca Server's Version, with a warning when the two Versions differ (expected after an Update until the APK is reinstalled, ADR 0001).

The page polls `GET /dashboard/status` (JSON, one key per section) every 2 s. That route asks camera-app for `/status` at most once a second, with a 1.5 s timeout, so a stopped camera-app shows as not Reachable within 2 to 4 s.

## Configuration

`config.toml` (the camera's address, the sensor geometry, the focuser arming, logging) lives in the user folder, not next to the code, so that a reinstall or an Update does not overwrite it (ADR 0002):

- Windows: `%APPDATA%\nex5r-ascom\config.toml`
- Mac: `~/Library/Application Support/nex5r-ascom/config.toml`
- Linux: `$XDG_CONFIG_HOME/nex5r-ascom/config.toml` (default `~/.config/...`)

On first launch the server creates it as a copy of `config-template.toml`; after that it always reads it from there and never rewrites it, so edit it by hand and restart the server. `app.py --help` prints the path. To start again from the template, delete it. An older `alpaca-server/config.toml` next to the code is no longer read: copy it to the user folder.

## Behaviour

- **Every exposure is a timed Bulb.** The mode dial must be on **M**. Before each exposure the server steps the shutter speed down until Bulb (`65535/1`).
- `ExposureMin` is 1 s.
- No shutter control: darks need the lens cap.
- **Gain = ISO**, in value mode: `GainMin`..`GainMax` from the camera, any value snapped to the nearest supported ISO. (List mode would make N.I.N.A. show indices.)
- **Image**: Bayer data of the ARW (`raw_image_visible`), RGGB, with `BayerOffset` derived from the file. Allow about 13 s of Wi-Fi transfer per image.
- **Subframes**: `StartX`, `NumX`, etc. are applied after download.
- Binning is 1 only.
- `sensor_type = 'mono'` in `config.toml` sends the same Bayer data as a monochrome sensor. N.I.N.A. 3.3 nightly's contrast-detection autofocus fails on the color image ("stride 9840 must be >= 29520"); use `mono` for daytime autofocus and `color` at night.
- No abort and no stop.

Focuser:

- **Absolute, positions 0..32** = lens offsets −16..+16 (`CameraEx.shiftFocusPosition`). It is for refining around a rough focus done beforehand (at 1-3 m, ±8 positions already cut sharpness by 10).
- **Position 16 = where the lens is when the focuser is armed.** The camera freezes if an offset is sent before any autofocus since the app started, so arming is a camera autofocus, and the app refuses offsets until armed. At Connect, the server arms if the camera is not armed yet.
- **Default arming: autofocus in `manual`, then focus mode `auto`** (`[focuser]` in `config.toml`: `arm_mode`, `drive_mode`, `arm_on_connect`). The autofocus in `manual` does not move the lens, so position 16 is the focus set by hand beforehand; in `auto` the offsets move the lens (in `manual` they are accepted but do nothing). With `arm_mode = 'auto'` the camera focuses first; an autofocus that fails (uniform target) leaves the lens about where it was.
- Action `arm` (Parameters `manual`, `auto`, `dmf`, or empty for `arm_mode`) arms again; positions from before no longer match. Changing the focus mode on the camera between moves breaks the drive.
- A move takes ~300 ms. No Halt, no temperature, `StepSize` unknown. The app refuses to move during an exposure, and to expose during a move.
- **Discovery**: Alpaca discovery on UDP 32227. The HTTP port is 11111.

## Usage

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py            # log in alpyca.log (and stdout)
.venv/bin/python smoke_test.py 2   # one 2 s exposure through the Alpaca API
.venv/bin/python app.py --config other.toml    # another configuration file instead of the user's config.toml
```

NEX5R Dev must be running on the camera (it turns Wi-Fi on and joins the network itself).

## Tests

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

No Camera needed: each test starts the Alpaca Server (`app.py --config`, or `app.py` alone with a temporary user folder) against a fake camera-app (`tests/fake_camera_app.py`, the routes of `nex5r.py` with camera-app's plain-text replies) and goes through the Alpaca API, as N.I.N.A. does. The fake serves `tests/data/sample.ARW`, a 64 x 40 DNG that rawpy decodes like an ARW (a real one is 16 MB), written by `tests/make_sample_arw.py`. The end-to-end test on the Camera stays manual: `smoke_test.py`.

## N.I.N.A. autofocus

### At night (star HFR, not tested on stars yet)

Before the session:

- `sensor_type = 'color'` in `config.toml`. If N.I.N.A. shows the "stride" error, switch to `mono`.
- Focus by hand first: at dusk, in MF, on a very distant object or a bright star with the screen magnifier (or the camera's AF on a distant object).
- Then connect the focuser. It arms itself (AF in `manual`, which leaves the lens alone, then `auto`): position 16 is your manual focus. Do not touch the focus ring afterwards (untested).
- Lens wide open (f/2.8): a narrower depth of focus gives a sharper V-curve.

Options → Imaging: Auto Focus = NINA or Hocus Focus (both measure star HFR).

Options → Autofocus:

| Setting | Value | Why |
|---|---|---|
| Method | Star HFR | |
| Initial offset steps | 4 | 9 points |
| Step size | 2 | sweep 8..24 around 16; by day ±8 cut sharpness by 10 |
| Default exposure | 2-3 s | 1 s minimum (Bulb) |
| Gain (ISO) | 800-1600 | lower it if bright stars saturate |
| Binning | 1×1 | the only one |
| Backlash | 0, method None | absolute positions; returning to 16 was repeatable |
| Focuser settle time | 0 | a move already waits for the camera (~250 ms) |
| Curve fitting | Hyperbolic (or Trends + Hyperbolic) | |
| Number of attempts | 2 | |
| Inner crop ratio | 0.6 | skips the distorted corner stars of the 30 mm |
| Use brightest n stars | 0 (all) | |
| Star detection | Normal or High sensitivity, no noise reduction | |

With Hocus Focus, keep "Max Blind Steps Per Direction" at 8 or less, or N.I.N.A. leaves the 0..32 range.

Sequencer trigger: no temperature sensor, so use "after HFR increase" (10-15 %) or "every 60-90 min".

To know:

- About 30 s per point (13 s of it Wi-Fi transfer): 4-5 min for 9 points.
- Best point near 0 or 32: the range is too short. Refocus by hand, reconnect the focuser to re-arm, run the autofocus again.
- The blur per step at infinity is not measured. After the first night run: if HFR barely changes across the sweep, use step size 3-4; if only the 2-3 central points give measurable stars, use 1.

### By day (contrast, tested 2026-11-20)

- Options → Imaging: Auto Focus = NINA (Hocus Focus only knows star HFR and returns 0).
- Options → Autofocus: Contrast Detection, ISO 100, 1 s (the default gain saturates in daylight).
- `sensor_type = 'mono'` (see Behaviour). On a textured scene at 1-3 m it converged to position 19 in about 5 min.
