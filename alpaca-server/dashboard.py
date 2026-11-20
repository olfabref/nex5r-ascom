"""The Dashboard: the Alpaca Server's status page, on the root (/) of the Alpaca port.

dashboard.html polls GET /dashboard/status every 2 s. That route returns one JSON object with one key
per section (see SECTIONS), plus the derived `version_mismatch`:

  {"server":     {"version": "0.1.0"},
   "camera_app": {"reachable": true, "version": "0.1.0", "error": null},
   "camera":     {"connected": false, "state": "IDLE", "exposing": false},
   "focuser":    {"connected": false, "armed": false, "position": 16, "moving": false},
   "settings":   {"camera_url": "http://192.168.0.10:8080", "sensor_type": "color", "editable": true,
                  "locked_by": []},
   "release":    {"state": "available", "update_available": true, "current": "0.1.0", "latest": "0.2.0",
                  "url": "https://github.com/.../releases/tag/v0.2.0", "checked_at": "...", "error": null},
   "update":     {"installable": true, "state": "idle", "version": null, "message": null, "command": null},
   "version_mismatch": false, "version_behind": null}

To show something new, add a section function to SECTIONS (and a renderer to dashboard.html).

To act on something (Arming, Update...), add an Action to ACTIONS (and a button to dashboard.html). The
page POSTs to /dashboard/action/<name> with a JSON body; the reply is {"ok": bool, "message": str}, and
the page shows the message:

  200  the Action ran; the message says what it did
  400  a confirm Action without "confirmed": true in the body, or a body that is not a JSON object
  404  no such Action
  409  refused: the Action cannot run now (its function raised exceptions.Refused('why'))
  415  not application/json, so a plain form on another site cannot trigger an Action

The confirmation is asked on the page and required again here.
"""
import json
import threading
import time
import urllib.parse
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Callable

import falcon
from falcon import App, Request, Response

import camera
import config
import devices
import focuser
import release
import update
from cameradevice import CameraState
from config import SENSOR_TYPES, Config
from exceptions import Refused
from nex5r import CameraError, Nex5r
from shr import log_request
from version import __version__

PAGE = Path(__file__).with_name('dashboard.html')

EXPOSURE_STATES = (CameraState.WAITING, CameraState.EXPOSING, CameraState.READING, CameraState.DOWNLOAD)

logger: Logger = None


class CameraAppProbe:
    """Whether camera-app is Reachable, and its Version: one GET /status at most every max_age seconds,
    shared by every open Dashboard, with a short timeout so that a stopped camera-app shows at once."""

    def __init__(self, url: str, timeout: float = 1.5, max_age: float = 1.0):
        self.timeout = timeout
        self.max_age = max_age
        self._lock = threading.Lock()
        self.retarget(url)

    def retarget(self, url: str):
        """camera-app at url from now on; the next state() asks it at once."""
        with self._lock:
            self.cam = Nex5r(url, timeout=self.timeout)
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


def _exposure_in_progress() -> bool:
    return camera.dev.state in EXPOSURE_STATES


def _camera() -> dict:
    dev = camera.dev
    return {'connected': dev.connected, 'state': dev.state.name, 'exposing': _exposure_in_progress()}


def _focuser() -> dict:
    dev = focuser.dev
    return {'connected': dev.connected, 'armed': dev.armed, 'position': dev.position, 'moving': dev.is_moving}


def _settings() -> dict:
    """The settings the page can edit (the 'settings' Action); editable while no Device is Connected."""
    locked_by = devices.connected()
    return {'camera_url': Config.camera_url, 'sensor_type': Config.sensor_type, 'editable': not locked_by,
            'locked_by': locked_by}


def _release() -> dict:
    """New Release detection (release.py): state is checking, available, up_to_date or cannot_check."""
    return release.checker.state()


def _update() -> dict:
    """The Update (update.py): installable (frozen on Windows) or the git command from the sources, and
    its state: idle, downloading, installing (the server quits and restarts) or failed (message)."""
    return update.updater.state()


# Section name -> function returning its JSON object. Order is the page's order.
SECTIONS = {
    'server': _server,
    'camera_app': _camera_app,
    'camera': _camera,
    'focuser': _focuser,
    'settings': _settings,
    'release': _release,
    'update': _update,
}


def status() -> dict:
    out = {name: section() for name, section in SECTIONS.items()}
    app = out['camera_app']
    # Only known when camera-app answers; an old camera-app without a Version is a mismatch too.
    out['version_mismatch'] = app['reachable'] and app['version'] != out['server']['version']
    out['version_behind'] = _behind(out['server']['version'], app['version']) if out['version_mismatch'] else None
    return out


def _behind(server: str, camera_app: str | None) -> str:
    """Which side of a Version mismatch is older: 'alpaca_server' or 'camera_app'. A camera-app with no
    or an unreadable Version counts as older, since it predates the shared Version (ADR 0001)."""
    def parse(v: str | None) -> tuple[int, ...] | None:
        try:
            return tuple(int(n) for n in v.split('-')[0].split('.'))
        except (AttributeError, ValueError):
            return None
    s, c = parse(server), parse(camera_app)
    return 'alpaca_server' if s is not None and c is not None and s < c else 'camera_app'


@dataclass(frozen=True)
class Action:
    run: Callable[[dict], str]      # the request's JSON body -> message for the page; raises Refused
    confirm: bool = False           # True: refused unless the body has "confirmed": true


def _refuse_while_connected(before: str):
    """Refused while a Device is Connected: the message asks to disconnect it in N.I.N.A. `before`..."""
    names = devices.connected()
    if names:
        raise Refused(f'{" and ".join(names)} Connected: disconnect {"them" if len(names) > 1 else "it"} '
                      f'in N.I.N.A. {before}')


def _arm_focuser(body: dict) -> str:
    """Arming with the config arm_mode and drive_mode, allowed even when the Focuser is Connected:
    the positions N.I.N.A. knows no longer match afterwards (hence the confirmation)."""
    if _exposure_in_progress():
        raise Refused('An exposure is in progress: arm the Focuser once it is over.')
    try:
        focuser.dev.arm()
    except (RuntimeError, CameraError) as e:
        raise Refused(f'Cannot arm the Focuser: {e}.')
    if not focuser.dev.armed:
        raise Refused('The Camera did not arm the Focuser: try again.')
    return f'Focuser armed at position {focuser.dev.position}.'


def _update_server(body: dict) -> str:
    """The Update stops the Alpaca Server: never while N.I.N.A. holds a Device. Returns once the download
    has started; the update section reports what follows."""
    _refuse_while_connected('first: the Update restarts the Alpaca Server.')
    return update.updater.start()


EDITABLE = ('camera_url', 'sensor_type')


def _camera_url(value) -> str:
    url = value.strip().rstrip('/') if isinstance(value, str) else ''
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'http' or not parts.hostname or parts.path or parts.query or parts.fragment:
        raise Refused(f'{value!r} is not a camera-app address such as http://192.168.0.10:8080.')
    try:
        parts.port
    except ValueError:
        raise Refused(f'{value!r} has an invalid port.')
    return url


def _use_camera_url(url: str):
    """Every client of camera-app talks to url from now on (no Device is Connected)."""
    devices.retarget(url)
    _probe.retarget(url)


def _save_settings(body: dict) -> str:
    """camera_url and/or sensor_type from the body, saved to the configuration file and applied at
    once. Only while no Device is Connected: N.I.N.A. reads the sensor type and talks to the Camera at
    Connect. Every other setting is edited in the file (and needs a restart)."""
    values = {k: v for k, v in body.items() if k != 'confirmed'}
    others = sorted(set(values) - set(EDITABLE))
    if others:
        raise Refused(f'Only camera_url and sensor_type can be changed here: edit {", ".join(others)} '
                      f'in {config.loaded_path} and restart the Alpaca Server.')
    if not values:
        raise Refused('Nothing to change: give camera_url and/or sensor_type.')
    _refuse_while_connected('before changing the settings.')
    if 'camera_url' in values:
        values['camera_url'] = _camera_url(values['camera_url'])
    if 'sensor_type' in values and values['sensor_type'] not in SENSOR_TYPES:
        raise Refused(f'sensor_type must be {" or ".join(map(repr, SENSOR_TYPES))}, not {values["sensor_type"]!r}.')
    changed = {k: v for k, v in values.items() if getattr(Config, k) != v}
    if not changed:
        return 'Settings unchanged.'
    try:
        config.save_device(**changed)
    except OSError as e:
        raise Refused(f'Cannot save {config.loaded_path}: {e}.')
    if 'camera_url' in changed:
        _use_camera_url(Config.camera_url)
    return 'Saved: ' + ', '.join(f'{k} = {v}' for k, v in changed.items()) + '.'


# Action name (last part of the URL, data-action of the page's button) -> Action.
ACTIONS = {
    'arm_focuser': Action(_arm_focuser, confirm=True),
    'settings': Action(_save_settings),
    'update': Action(_update_server, confirm=True),
}


def _reply(resp: Response, code: str, ok: bool, message: str):
    resp.status = code
    resp.content_type = 'application/json'
    resp.cache_control = ['no-store']
    resp.text = json.dumps({'ok': ok, 'message': message})


class action_route:
    def on_post(self, req: Request, resp: Response, name: str):
        log_request(req)
        act = ACTIONS.get(name)
        if act is None:
            return _reply(resp, falcon.HTTP_404, False, f'Unknown action {name!r}.')
        if not (req.content_type or '').startswith('application/json'):
            return _reply(resp, falcon.HTTP_415, False, 'The body must be application/json.')
        try:
            body = req.get_media(default_when_empty={})
        except falcon.HTTPError:
            body = None
        if not isinstance(body, dict):
            return _reply(resp, falcon.HTTP_400, False, 'The body must be a JSON object.')
        if act.confirm and body.get('confirmed') is not True:
            return _reply(resp, falcon.HTTP_400, False, 'This action needs a confirmation ("confirmed": true).')
        try:
            message = act.run(body)
        except Refused as e:
            logger.warning(f'[dashboard] {name} refused: {e}')
            return _reply(resp, falcon.HTTP_409, False, str(e))
        logger.info(f'[dashboard] {name}: {message}')
        _reply(resp, falcon.HTTP_200, True, message)


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


def add_routes(app: App, lgr: Logger):
    """The Dashboard's routes; call after the Devices are started (camera.dev, focuser.dev) and the
    release check (release.start())."""
    global _probe, logger
    logger = lgr
    _probe = CameraAppProbe(Config.camera_url)
    app.add_route('/', page())
    app.add_route('/dashboard/status', status_route())
    app.add_route('/dashboard/action/{name}', action_route())
