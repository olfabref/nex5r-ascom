"""The Dashboard: the Alpaca Server's status page, on the root (/) of the Alpaca port.

dashboard.html polls GET /dashboard/status every 2 s. That route returns one JSON object with one key
per section (see SECTIONS), plus the derived `version_mismatch`:

  {"server":     {"version": "0.1.0"},
   "camera_app": {"reachable": true, "version": "0.1.0", "error": null},
   "camera":     {"connected": false, "state": "IDLE", "exposing": false},
   "focuser":    {"connected": false, "armed": false, "position": 16, "moving": false},
   "release":    {"state": "available", "update_available": true, "current": "0.1.0", "latest": "0.2.0",
                  "url": "https://github.com/.../releases/tag/v0.2.0", "checked_at": "...", "error": null},
   "version_mismatch": false}

To show something new, add a section function to SECTIONS (and a renderer to dashboard.html).

To act on something (Arming, Update...), add an Action to ACTIONS (and a button to dashboard.html). The
page POSTs to /dashboard/action/<name> with a JSON body; the reply is {"ok": bool, "message": str}, and
the page shows the message:

  200  the Action ran; the message says what it did
  400  a confirm Action without "confirmed": true in the body, or a body that is not a JSON object
  404  no such Action
  409  refused: the Action cannot run now (its function raised Refused('why'))
  415  not application/json, so a plain form on another site cannot trigger an Action

The confirmation is asked on the page and required again here.
"""
import json
import threading
import time
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Callable

import falcon
from falcon import App, Request, Response

import camera
import focuser
import release
from cameradevice import CameraState
from config import Config
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


def _exposure_in_progress() -> bool:
    return camera.dev.state in EXPOSURE_STATES


def _camera() -> dict:
    dev = camera.dev
    return {'connected': dev.connected, 'state': dev.state.name, 'exposing': _exposure_in_progress()}


def _focuser() -> dict:
    dev = focuser.dev
    return {'connected': dev.connected, 'armed': dev.armed, 'position': dev.position, 'moving': dev.is_moving}


def _release() -> dict:
    """New Release detection (release.py): state is checking, available, up_to_date or cannot_check."""
    return release.checker.state()


# Section name -> function returning its JSON object. Order is the page's order.
SECTIONS = {
    'server': _server,
    'camera_app': _camera_app,
    'camera': _camera,
    'focuser': _focuser,
    'release': _release,
}


def status() -> dict:
    out = {name: section() for name, section in SECTIONS.items()}
    app = out['camera_app']
    # Only known when camera-app answers; an old camera-app without a Version is a mismatch too.
    out['version_mismatch'] = app['reachable'] and app['version'] != out['server']['version']
    return out


class Refused(Exception):
    """An Action that cannot run now; its message is the refusal shown on the page."""


@dataclass(frozen=True)
class Action:
    run: Callable[[dict], str]      # the request's JSON body -> message for the page; raises Refused
    confirm: bool = False           # True: refused unless the body has "confirmed": true


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
        raise Refused('The camera did not arm the Focuser: try again.')
    return f'Focuser armed at position {focuser.dev.position}.'


# Action name (last part of the URL, data-action of the page's button) -> Action.
ACTIONS = {
    'arm_focuser': Action(_arm_focuser, confirm=True),
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
