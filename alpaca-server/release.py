"""New Release detection: which Release is the latest on GitHub, and whether it is newer than this Version.

- latest_release() asks the GitHub API once and returns the latest Release, with its assets (the Update
  downloads the installer and SHA256SUMS from there). Drafts and prereleases are never "latest".
- ReleaseCheck runs latest_release() in a background thread at startup, then every 6 h, and keeps the
  outcome for the Dashboard (state()) and the tray icon (update_available, on_change). Nothing is
  installed: the Update is started by hand from the Dashboard.

Without network the check just reports "cannot check": it never blocks or stops the Alpaca Server.
The NEX5R_RELEASES_URL environment variable points the lookup elsewhere (the tests' fake GitHub).
"""
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from version import __version__

RELEASES_URL = os.environ.get('NEX5R_RELEASES_URL',
                              'https://api.github.com/repos/olfabref/nex5r-ascom/releases/latest')
CHECK_INTERVAL = 6 * 3600.0     # seconds between two checks
TIMEOUT = 10.0                  # seconds for one GitHub request

# ReleaseCheck states
CHECKING = 'checking'           # the first check is not over yet
AVAILABLE = 'available'         # a newer Release exists
UP_TO_DATE = 'up_to_date'       # the latest Release is this Version or older, or there is no Release
CANNOT_CHECK = 'cannot_check'   # GitHub not reachable or an unexpected answer

logger: logging.Logger | None = None    # set by start(); falls back to this module's logger


class ReleaseError(Exception):
    """The latest Release could not be found out (no network, GitHub error, unexpected answer)."""


@dataclass(frozen=True)
class Asset:
    name: str
    url: str        # browser_download_url
    size: int


@dataclass(frozen=True)
class Release:
    version: str    # 'X.Y.Z', without the tag's 'v'
    tag: str        # 'vX.Y.Z'
    url: str        # the Release's GitHub page
    assets: tuple[Asset, ...]

    def asset(self, name: str) -> Asset | None:
        """The asset called name, if the Release has one."""
        return next((a for a in self.assets if a.name == name), None)


def parse_version(text: str) -> tuple[int, int, int]:
    """'vX.Y.Z' or 'X.Y.Z' -> (X, Y, Z); ReleaseError on anything else."""
    parts = text.strip().removeprefix('v').split('.')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ReleaseError(f'not a Version: {text!r}')
    return int(parts[0]), int(parts[1]), int(parts[2])


def is_newer(version: str, than: str) -> bool:
    return parse_version(version) > parse_version(than)


def latest_release(url: str = RELEASES_URL, timeout: float = TIMEOUT) -> Release | None:
    """The latest Release on GitHub, or None when the repository has none yet; ReleaseError otherwise."""
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': f'nex5r-ascom/{__version__}',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise ReleaseError(f'GitHub answered HTTP {e.code}') from e
    except (OSError, ValueError) as e:      # URLError, timeouts and resets are OSErrors; bad JSON
        raise ReleaseError(f'cannot reach GitHub: {getattr(e, "reason", e)}') from e
    try:
        tag = body['tag_name']
        assets = tuple(Asset(a['name'], a['browser_download_url'], int(a['size'])) for a in body['assets'])
        return Release('.'.join(map(str, parse_version(tag))), tag, body['html_url'], assets)
    except (KeyError, TypeError, ValueError) as e:
        raise ReleaseError(f'unexpected GitHub answer: {e!r}') from e


class ReleaseCheck:
    """The outcome of the last lookup of the latest Release, refreshed every `interval` seconds."""

    def __init__(self, current: str = __version__, url: str = RELEASES_URL, interval: float = CHECK_INTERVAL,
                 fetch: Callable[..., Release | None] = latest_release, timeout: float = TIMEOUT):
        self.current = current
        self.url = url
        self.interval = interval
        self.timeout = timeout
        self._fetch = fetch
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state = CHECKING
        self._latest: Release | None = None
        self._error: str | None = None
        self._checked_at: str | None = None
        # Called with state() from the checking thread whenever the state or the latest Version changes.
        self.on_change: list[Callable[[dict], None]] = []

    def start(self) -> 'ReleaseCheck':
        threading.Thread(target=self._run, name='release-check', daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while True:
            self.check()
            if self._stop.wait(self.interval):
                return

    def check(self) -> dict:
        """Looks up the latest Release now; returns state()."""
        try:
            latest, error = self._fetch(self.url, timeout=self.timeout), None
            state = AVAILABLE if latest and is_newer(latest.version, self.current) else UP_TO_DATE
        except ReleaseError as e:
            latest, error, state = None, str(e), CANNOT_CHECK
        except Exception as e:                  # never let the check thread die
            latest, error, state = None, f'{type(e).__name__}: {e}', CANNOT_CHECK
        with self._lock:
            changed = (state, latest) != (self._state, self._latest)
            self._state, self._latest, self._error = state, latest, error
            self._checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        log = logger or logging.getLogger(__name__)
        if state == CANNOT_CHECK:
            log.info(f'[release] cannot check for a new Release: {error}')
        elif changed:
            log.info(f'[release] {"new Release " + latest.tag + " available" if state == AVAILABLE else "up to date"}'
                     f' (this Version {self.current})')
        out = self.state()
        if changed:
            for callback in list(self.on_change):
                try:
                    callback(out)
                except Exception:
                    log.exception('[release] on_change callback failed')
        return out

    @property
    def latest(self) -> Release | None:
        """The latest Release found by the last check (None: none, or it could not check)."""
        with self._lock:
            return self._latest

    @property
    def update_available(self) -> bool:
        with self._lock:
            return self._state == AVAILABLE

    def state(self) -> dict:
        with self._lock:
            rel = self._latest
            return {'state': self._state, 'update_available': self._state == AVAILABLE,
                    'current': self.current, 'latest': rel.version if rel else None,
                    'url': rel.url if rel else None, 'checked_at': self._checked_at, 'error': self._error}


checker: ReleaseCheck | None = None


def start(log: logging.Logger | None = None) -> ReleaseCheck:
    """Starts the background check (at startup, then every 6 h); the running one is `checker`."""
    global checker, logger
    logger = log
    checker = ReleaseCheck().start()
    return checker
