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
- `config.toml`: the camera's address and the sensor geometry.

## Behaviour

- **Every exposure is a timed Bulb.** The mode dial must be on **M**. Before each exposure the server steps the shutter speed down until Bulb (`65535/1`).
- `ExposureMin` is 1 s.
- No shutter control: darks need the lens cap.
- **Gain = ISO**, in value mode: `GainMin`..`GainMax` from the camera, any value snapped to the nearest supported ISO. (List mode would make N.I.N.A. show indices.)
- **Image**: Bayer data of the ARW (`raw_image_visible`), RGGB, with `BayerOffset` derived from the file. Allow about 13 s of Wi-Fi transfer per image.
- **Subframes**: `StartX`, `NumX`, etc. are applied after download.
- Binning is 1 only.
- `sensor_type = 'mono'` in `config.toml` sends the same Bayer data as a monochrome sensor. N.I.N.A. 3.3 nightly's contrast-detection autofocus fails on the color image ("stride 9840 must be >= 29520"); use `mono` for daytime autofocus and `color` at night.
- Daytime autofocus in N.I.N.A.: Contrast Detection, built-in autofocus (not Hocus Focus, which only knows star HFR), ISO 100 and 1 s (the default gain saturates in daylight).
- No abort and no stop.

Focuser:

- **Absolute, positions 0..32** = lens offsets −16..+16 (`CameraEx.shiftFocusPosition`). The window is small and the steps fine: it is for refining, the rough focus is done beforehand.
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
```

NEX5R Dev must be running on the camera (it turns Wi-Fi on and joins the network itself).
