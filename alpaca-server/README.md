# alpaca-server

ASCOM Alpaca server for the Sony NEX-5R: exposes the camera to N.I.N.A. (or any Alpaca client) as a `Camera` device (ICameraV4). It talks to `camera-app`, the app running on the camera, over Wi-Fi.

Based on the official ASCOM [AlpycaDevice](https://github.com/ASCOMInitiative/AlpycaDevice) template (MIT, see `LICENSE-AlpycaDevice.txt`). `app.py`, `config.py`, `discovery.py`, `exceptions.py`, `log.py`, `management.py`, `setup.py` and `shr.py` come from it, with small changes marked `nex5r-ascom`:
- a threaded WSGI server;
- the Camera device instead of the Rotator;
- a routing filter.

## Files

- `camera.py`: Alpaca responders. ImageBytes when the client accepts it, JSON otherwise.
- `cameradevice.py`: one exposure at a time on a worker thread: Bulb, ISO, `/capture`, wait for the ARW, download, rawpy decoding.
- `nex5r.py`: HTTP client for camera-app (`/status`, `/shutter`, `/iso`, `/capture?ms=`, `/files`, `/dcim/`).
- `config.toml`: the camera's address and the sensor geometry.

## Behaviour

- **Every exposure is a timed Bulb.** The mode dial must be on **M**. Before each exposure the server steps the shutter speed down until Bulb (`65535/1`).
- `ExposureMin` is 1 s.
- No shutter control: darks need the lens cap.
- **Gain = ISO**, in value mode: `GainMin`..`GainMax` from the camera, any value snapped to the nearest supported ISO. (List mode would make N.I.N.A. show indices.)
- **Image**: Bayer data of the ARW (`raw_image_visible`), RGGB, with `BayerOffset` derived from the file. Allow about 13 s of Wi-Fi transfer per image.
- **Subframes**: `StartX`, `NumX`, etc. are applied after download.
- Binning is 1 only.
- No abort and no stop.
- **Discovery**: Alpaca discovery on UDP 32227. The HTTP port is 11111.

## Usage

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py            # log in alpyca.log (and stdout)
.venv/bin/python smoke_test.py 2   # one 2 s exposure through the Alpaca API
```

NEX5R Dev must be running on the camera (launched from Tweak so it joins the Wi-Fi).
