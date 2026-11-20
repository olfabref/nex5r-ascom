"""The tray icon of the Alpaca Server: in the Windows system tray, or the Mac menu bar (from the sources).

It shows that the server is running (and its Version), flags a new Release (release.checker), opens the
Dashboard in the browser and quits the server. pystray needs the main thread (AppKit on Mac), so
app.main serves HTTP on another thread while run() blocks here.

The icon is optional: `app.py --no-tray` (tests, CI) never imports pystray, and when no tray can be
shown (no desktop session, pystray missing) run() logs why and returns False: the server keeps serving.
"""
import logging
import webbrowser
from typing import Callable

from PIL import Image, ImageDraw

NAME = 'nex5r-ascom'
SIZE = 64


def dashboard_url(ip_address: str, port: int) -> str:
    """The Dashboard as seen from this machine: listening on every address ('') means localhost."""
    host = ip_address if ip_address not in ('', '0.0.0.0') else '127.0.0.1'
    if host == '::':
        host = '::1'
    if ':' in host:
        host = f'[{host}]'
    return f'http://{host}:{port}/'


def icon_image(update_available: bool = False) -> Image.Image:
    """A camera lens (dark ring, green centre: running), with an orange badge when a Release is available."""
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, SIZE - 4, SIZE - 4), fill=(40, 44, 52, 255), outline=(200, 205, 215, 255), width=4)
    draw.ellipse((20, 20, SIZE - 20, SIZE - 20), fill=(60, 190, 110, 255))
    if update_available:
        draw.ellipse((SIZE - 26, 0, SIZE, 26), fill=(245, 150, 30, 255), outline=(255, 255, 255, 255), width=3)
    return img


class Tray:
    def __init__(self, url: str, version: str, quit: Callable[[], None], checker=None,
                 logger: logging.Logger | None = None):
        """url: the Dashboard; quit: stops the server (called on the tray's thread before the icon goes);
        checker: a release.ReleaseCheck, or None."""
        self.url = url
        self.version = version
        self._quit = quit
        self._checker = checker
        self._log = logger or logging.getLogger(__name__)
        self._icon = None

    # -- what the tray shows
    def _update(self) -> bool:
        return bool(self._checker and self._checker.update_available)

    def _latest(self) -> str | None:
        latest = self._checker.latest if self._checker else None
        return latest.version if latest else None

    def title(self) -> str:
        text = f'{NAME} Alpaca Server {self.version}: running'
        if self._update():
            text += f'\nVersion {self._latest()} available'
        return text

    # -- menu actions
    def open_dashboard(self, *_):
        webbrowser.open(self.url)

    def quit(self, icon=None, *_):
        self._log.info('==SHUTDOWN== Quit from the tray icon')
        try:
            self._quit()
        finally:
            (icon or self._icon).stop()

    def _refresh(self, *_):
        """From the Release check thread: marshal to the tray's thread where the platform needs it."""
        icon = self._icon
        if icon is None:
            return

        def apply():
            icon.icon = icon_image(self._update())
            icon.title = self.title()
            icon.update_menu()
        if type(icon).__module__ == 'pystray._darwin':      # AppKit: only from the main thread
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(apply)
                return
            except ImportError:
                pass
        apply()

    def run(self) -> bool:
        """Shows the icon and blocks until Quit (True), or returns False at once when no tray can be shown."""
        if self._checker:       # before the icon reads the state: no change can slip in between
            self._checker.on_change.append(self._refresh)
        try:
            import pystray
            item = pystray.MenuItem
            self._icon = pystray.Icon(NAME, icon_image(self._update()), self.title(), menu=pystray.Menu(
                item(lambda _: f'Alpaca Server {self.version}: running', None, enabled=False),
                item(lambda _: f'Version {self._latest()} available', self.open_dashboard,
                     visible=lambda _: self._update()),
                item('Open Dashboard', self.open_dashboard, default=True),
                pystray.Menu.SEPARATOR,
                item('Quit', self.quit),
            ))
            self._log.info(f'[tray] icon shown, Dashboard at {self.url}')
            self._icon.run()
            return True
        except Exception as e:
            self._log.warning(f'[tray] no tray icon ({type(e).__name__}: {e}); the server runs without it')
            if self._checker and self._refresh in self._checker.on_change:
                self._checker.on_change.remove(self._refresh)
            self._icon = None
            return False
