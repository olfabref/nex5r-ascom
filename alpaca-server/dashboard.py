"""The Dashboard: the Alpaca Server's status page, on the root (/) of the Alpaca port.

dashboard.html polls GET /dashboard/status every 2 s. That route returns one JSON object with one key
per section (see SECTIONS), plus the derived `version_mismatch`:

  {"server":     {"version": "0.1.0"},
   "camera_app": {"reachable": true, "version": "0.1.0", "error": null},
   "camera":     {"connected": false, "state": "IDLE", "exposing": false},
   "focuser":    {"connected": false, "armed": false, "position": 16, "moving": false},
   "version_mismatch": false}

To show something new, add a section function to SECTIONS (and a renderer to dashboard.html); to act
on something (Update, Arming...), add a route in add_routes.
"""
import json
import threading
import time
from pathlib import Path

from falcon import App, Request, Response

import camera
import focuser
from cameradevice import CameraState
from config import Config
from nex5r import CameraError, Nex5r
from shr import log_request
from version import __version__

PAGE = Path(__file__).with_name('dashboard.html')

EXPOSURE_STATES = (CameraState.WAITING, CameraState.EXPOSING, CameraState.READING, CameraState.DOWNLOAD)


class CameraAppProbe:
    """Whether camera-app is Reachable, and its Version: one GET /status at most every max_age seconds,
    shared by every open Dashboard, with a short timeout so that a stopped camera-app shows at once."""

    def __init__(self, url: str, timeout: float = 1.5, max_age: float = 1.0):
        self.cam = Nex5r(url, timeout=timeout)
        self.max_age = max_age
        self._lock = threading.Lock()
        self._at = float('-inf')
        self._state: dict = {}

    def state(self) -> dict:
        with self._lock:
            if time.monotonic() - self._at >= self.max_age:
                try:
                    st = self.cam.status()
                    self._state = {'reachable': True, 'version': st.get('version'), 'error': None}
                except CameraError as e:
                    self._state = {'reachable': False, 'version': None, 'error': str(e)}
                self._at = time.monotonic()
            return dict(self._state)


_probe: CameraAppProbe | None = None


def _server() -> dict:
    return {'version': __version__}


def _camera_app() -> dict:
    return _probe.state()


def _camera() -> dict:
    dev = camera.dev
    return {'connected': dev.connected, 'state': dev.state.name, 'exposing': dev.state in EXPOSURE_STATES}


def _focuser() -> dict:
    dev = focuser.dev
    return {'connected': dev.connected, 'armed': dev.armed, 'position': dev.position, 'moving': dev.is_moving}


# Section name -> function returning its JSON object. Order is the page's order.
SECTIONS = {
    'server': _server,
    'camera_app': _camera_app,
    'camera': _camera,
    'focuser': _focuser,
}


def status() -> dict:
    out = {name: section() for name, section in SECTIONS.items()}
    app = out['camera_app']
    # Only known when camera-app answers; an old camera-app without a Version is a mismatch too.
    out['version_mismatch'] = app['reachable'] and app['version'] != out['server']['version']
    return out


class page:
    def on_get(self, req: Request, resp: Response):
        log_request(req)
        resp.content_type = 'text/html; charset=utf-8'
        resp.text = PAGE.read_text(encoding='utf-8')


class status_route:
    def on_get(self, req: Request, resp: Response):
        log_request(req)
        resp.content_type = 'application/json'
        resp.cache_control = ['no-store']
        resp.text = json.dumps(status())


def add_routes(app: App):
    """The Dashboard's routes; call after the Devices are started (camera.dev, focuser.dev)."""
    global _probe
    _probe = CameraAppProbe(Config.camera_url)
    app.add_route('/', page())
    app.add_route('/dashboard/status', status_route())
