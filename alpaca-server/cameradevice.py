"""NEX-5R camera logic behind the Alpaca Camera responders (camera.py).

One exposure at a time, on a worker thread:
  Bulb check -> ISO -> /capture (the app closes the shutter after the duration) -> wait for the new
  ARW on the card -> download -> rawpy Bayer data -> ImageReady.
Every exposure is a timed Bulb (see brief.md); "dark" frames need the lens cap (no shutter control).
"""
import io
import threading
import time
from datetime import datetime, timezone
from enum import IntEnum
from logging import Logger

import numpy as np
import rawpy

from nex5r import CameraError, Nex5r


class CameraState(IntEnum):
    IDLE = 0
    WAITING = 1
    EXPOSING = 2
    READING = 3
    DOWNLOAD = 4
    ERROR = 5


class CameraDevice:
    def __init__(self, logger: Logger, url: str, file_timeout: float):
        self.logger = logger
        self.cam = Nex5r(url)
        self.file_timeout = file_timeout
        self._lock = threading.Lock()
        self.connected = False
        self.state = CameraState.IDLE
        self.error: str | None = None
        self.image: np.ndarray | None = None      # shape (X, Y) as Alpaca wants, int32
        self.bayer_offset: tuple[int, int] | None = None
        self.last_duration: float | None = None
        self.last_start: str | None = None
        self._start_mono = 0.0
        self._duration = 0.0
        self.isos: list[int] = []
        self.gain_index = 0
        self._applied_iso: int | None = None

    # --- connection -------------------------------------------------------------------------

    def connect(self):
        st = self.cam.status()                    # raises CameraError when unreachable
        self.isos = self.cam.isos()
        try:
            cur = int(st.get('iso', ''))
            self.gain_index = self.isos.index(cur)
            self._applied_iso = cur
        except ValueError:
            self.gain_index = 0
        self.connected = True
        self.logger.info(f'[camera] connected: {st}')

    def disconnect(self):
        self.connected = False

    # --- exposure ---------------------------------------------------------------------------

    @property
    def image_ready(self) -> bool:
        return self.image is not None and self.state == CameraState.IDLE

    def percent_completed(self) -> int:
        if self.state == CameraState.EXPOSING and self._duration > 0:
            return min(99, int(100 * (time.monotonic() - self._start_mono) / self._duration))
        if self.state in (CameraState.READING, CameraState.DOWNLOAD):
            return 99
        return 100 if self.image is not None else 0

    def start_exposure(self, duration: float):
        with self._lock:
            if self.state not in (CameraState.IDLE, CameraState.ERROR):
                raise RuntimeError('an exposure is already running')
            self.image = None
            self.error = None
            self.state = CameraState.WAITING
            self._duration = duration
        threading.Thread(target=self._run, args=(duration,), daemon=True).start()

    def _run(self, duration: float):
        try:
            self.cam.ensure_bulb()
            iso = self.isos[self.gain_index] if self.isos else None
            if iso is not None and iso != self._applied_iso:
                self.cam.set_iso(iso)
                self._applied_iso = iso
            previous = self.cam.newest_arw()
            previous_name = previous[0] if previous else None

            self.last_start = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            self._start_mono = time.monotonic()
            self.state = CameraState.EXPOSING
            self.cam.capture(int(round(duration * 1000)))
            self.logger.info(f'[camera] exposing {duration} s at ISO {iso}')
            time.sleep(max(0.0, duration - (time.monotonic() - self._start_mono)))

            self.state = CameraState.READING
            name = self.cam.wait_new_arw(previous_name, self.file_timeout)
            self.state = CameraState.DOWNLOAD
            t0 = time.monotonic()
            data = self.cam.download(name)
            self.logger.info(f'[camera] {name}: {len(data)} B in {time.monotonic() - t0:.1f} s')
            self.image, self.bayer_offset = decode_arw(data)
            self.last_duration = duration
            self.state = CameraState.IDLE
        except Exception as e:                   # CameraError, rawpy errors, anything else
            self.error = str(e)
            self.state = CameraState.ERROR
            self.logger.error(f'[camera] exposure failed: {e}')


def decode_arw(data: bytes) -> tuple[np.ndarray, tuple[int, int]]:
    """Raw Bayer data of the visible area as an (X, Y) int32 array, and the (x, y) offset of red."""
    with rawpy.imread(io.BytesIO(data)) as raw:
        visible = raw.raw_image_visible.astype(np.int32)       # (rows, cols) = (Y, X)
        pattern = raw.raw_pattern                               # 2x2 color indices
        desc = raw.color_desc.decode()                          # e.g. "RGBG"
    red = desc.index('R')
    ys, xs = np.nonzero(pattern == red)
    return np.ascontiguousarray(visible.T), (int(xs[0]), int(ys[0]))
