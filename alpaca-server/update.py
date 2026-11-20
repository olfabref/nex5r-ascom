"""The Update of the Alpaca Server (ADR 0002), started from the Dashboard.

On Windows (the frozen executable), Updater.start() looks up the latest Release (release.latest_release),
then a background thread downloads its installer and SHA256SUMS, checks the installer's SHA-256, launches
it detached in silent mode and quits the Alpaca Server. The installer stops whatever is left of it,
installs, and starts the new one; the configuration in the user folder is never touched. A wrong
SHA-256 or a failed download cancels the Update: the Alpaca Server keeps running and state() says why.

From the sources (Mac, or Windows without the installer), nothing is run: start() returns the git
command to type. camera-app is not part of the Update.
"""
import hashlib
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

import release
from exceptions import Refused
from version import __version__

INSTALLER = 'nex5r-ascom-setup.exe'     # the Release asset (alpaca-server/installer/nex5r-ascom.iss)
SUMS = 'SHA256SUMS'
SILENT = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
TIMEOUT = 30.0                          # seconds without data before a download is given up
SOURCES = Path(__file__).resolve().parent.parent        # the git checkout, when run from the sources

# Updater states
IDLE = 'idle'                   # no Update started since the Alpaca Server started
DOWNLOADING = 'downloading'
INSTALLING = 'installing'       # the installer is launched: the Alpaca Server quits, then restarts
FAILED = 'failed'               # cancelled: the Alpaca Server keeps running; `message` says why


def frozen_windows() -> bool:
    """True for the frozen executable on Windows, the only one an installer can replace (ADR 0002)."""
    return sys.platform == 'win32' and bool(getattr(sys, 'frozen', False))


def sources_command() -> str:
    return f'git -C "{SOURCES}" pull'


class UpdateError(Exception):
    """The Update was cancelled (download failed, wrong SHA-256...); the Alpaca Server keeps running."""


def launch_detached(exe: Path, args: list[str]):
    """Starts the installer outside the Alpaca Server's process tree, so that it outlives the Alpaca
    Server it stops."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    kw = dict(cwd=exe.parent, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL)
    try:    # also out of the job of whoever started the Alpaca Server, when that job allows it
        subprocess.Popen([str(exe), *args], creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:
        subprocess.Popen([str(exe), *args], creationflags=flags, **kw)


def parse_sums(text: str) -> dict[str, str]:
    """SHA256SUMS (`sha256sum` format: '<hex>  name', or '<hex> *name') -> name -> lowercase hex."""
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            sums[parts[1].lstrip('*')] = parts[0].lower()
    return sums


def download(url: str, to: Path, timeout: float = TIMEOUT) -> str:
    """Saves url into `to`; returns its SHA-256 (hex). UpdateError when it cannot be downloaded."""
    req = release.http_request(url)
    digest = hashlib.sha256()
    try:
        with release.open_url(req, timeout) as r, open(to, 'wb') as f:
            while chunk := r.read(1 << 16):
                digest.update(chunk)
                f.write(chunk)
    except (OSError, ValueError) as e:      # HTTPError, URLError and timeouts are OSErrors
        raise UpdateError(f'cannot download {to.name}: {getattr(e, "reason", e)}') from e
    return digest.hexdigest()


class Updater:
    def __init__(self, current: str = __version__, url: str = release.RELEASES_URL,
                 installable: bool | None = None, launch: Callable[[Path, list[str]], None] = launch_detached,
                 quit: Callable[[], None] | None = None, workdir: Path | None = None,
                 logger: logging.Logger | None = None):
        """launch(exe, args) starts the installer; quit() stops the Alpaca Server (app.main's clean quit);
        workdir: where the installer is downloaded (default: a new temporary folder)."""
        self.current = current
        self.url = url
        self.installable = frozen_windows() if installable is None else installable
        self._launch = launch
        self._quit = quit
        self._workdir = workdir
        self._log = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state, self._version, self._message = IDLE, None, None

    def state(self) -> dict:
        with self._lock:
            return {'installable': self.installable, 'state': self._state, 'version': self._version,
                    'message': self._message, 'command': None if self.installable else sources_command()}

    def _set(self, state: str, message: str | None):
        with self._lock:
            self._state, self._message = state, message

    def start(self) -> str:
        """Starts the Update and returns what the page shows; Refused when it cannot start now."""
        if not self.installable:
            return (f'Running from the sources: nothing was run. To update, type {sources_command()}, '
                    'then restart the Alpaca Server.')
        with self._lock:
            if self._state in (DOWNLOADING, INSTALLING):
                raise Refused(f'An Update to Version {self._version} is already in progress.')
        try:
            latest = release.latest_release(self.url)
        except release.ReleaseError as e:
            raise Refused(f'Cannot look up the latest Release: {e}.')
        if latest is None or not release.is_newer(latest.version, self.current):
            raise Refused(f'Version {self.current} is up to date: no newer Release.')
        installer, sums = latest.asset(INSTALLER), latest.asset(SUMS)
        if installer is None or sums is None:
            raise Refused(f'Release {latest.tag} has no {INSTALLER} or no {SUMS}.')
        with self._lock:
            self._state, self._version = DOWNLOADING, latest.version
            self._message = f'Downloading Version {latest.version}…'
        self._thread = threading.Thread(target=self._run, args=(latest, installer, sums),
                                        name='update', daemon=True)
        self._thread.start()
        return f'Update to Version {latest.version} started: downloading the installer.'

    def wait(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    def _run(self, latest: release.Release, installer: release.Asset, sums: release.Asset):
        folder = self._workdir or Path(tempfile.mkdtemp(prefix='nex5r-ascom-update-'))
        exe = folder / INSTALLER
        try:
            download(sums.url, folder / SUMS)
            expected = parse_sums((folder / SUMS).read_text(encoding='utf-8', errors='replace')).get(INSTALLER)
            if expected is None:
                raise UpdateError(f'{SUMS} of {latest.tag} has no line for {INSTALLER}')
            actual = download(installer.url, exe)
            if actual != expected:
                raise UpdateError(f'wrong SHA-256 for {INSTALLER} of {latest.tag}: {actual}, '
                                  f'{SUMS} says {expected}')
            self._set(INSTALLING, f'Installing Version {latest.version}: the Alpaca Server restarts.')
            self._log.info(f'[update] {INSTALLER} of {latest.tag} checked (SHA-256 {actual}): '
                           f'running it silently, then quitting')
            self._launch(exe, [*SILENT, f'/LOG={folder / "install.log"}'])
        except Exception as e:
            exe.unlink(missing_ok=True)
            if self._workdir is None:
                shutil.rmtree(folder, ignore_errors=True)
            why = str(e) if isinstance(e, UpdateError) else f'{type(e).__name__}: {e}'
            self._set(FAILED, f'Update cancelled: {why}. The Alpaca Server keeps running Version {self.current}.')
            self._log.error(f'[update] cancelled: {why}')
            return
        self._log.info('==SHUTDOWN== Update: quitting for the installer')
        if self._quit:
            self._quit()


updater: Updater | None = None


def start(log: logging.Logger | None = None, quit: Callable[[], None] | None = None) -> Updater:
    """Creates the Alpaca Server's Updater (`updater`); quit() stops the Alpaca Server once the installer
    is launched."""
    global updater
    updater = Updater(quit=quit, logger=log)
    return updater
