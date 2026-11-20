"""HTTP client for camera-app, the app running on the NEX-5R (see camera-app HttpServer.java).

The camera answers in plain text ("key=value" lines for /status). Everything here blocks; the caller
runs it off the Alpaca request threads.
"""
import time
import urllib.parse
import urllib.request


class CameraError(Exception):
    """The camera is unreachable or refused a command."""


class Nex5r:
    BULB = '65535/1'
    MAX_SHUTTER_STEPS = 45          # 1/4000 -> Bulb is 52 third-stops; from 1/30 it took 31

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base = base_url.rstrip('/')
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None) -> bytes:
        url = self.base + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=timeout or self.timeout) as r:
                return r.read()
        except Exception as e:      # URLError, timeouts, HTTP 4xx/5xx
            raise CameraError(f'GET {path} failed: {e}') from e

    def _text(self, path: str, params: dict | None = None) -> str:
        return self._get(path, params).decode('utf-8', 'replace')

    def status(self) -> dict:
        """/status as a dict: ip, shutter, bulb, exposing, iso, isos, inhibition, last."""
        out = {}
        for line in self._text('/status').splitlines():
            k, sep, v = line.partition('=')
            if sep:
                out[k.strip()] = v.strip()
        return out

    def isos(self) -> list[int]:
        """Supported ISO values, without 0 (ISO Auto, which the camera does list in M)."""
        raw = self.status().get('isos', '')
        try:
            return sorted(i for i in (int(v) for v in raw.split(",") if v.strip()) if i > 0)
        except ValueError:
            raise CameraError(f'unexpected isos value {raw!r}')

    def iso(self) -> int:
        try:
            return int(self.status().get('iso', ''))
        except ValueError:
            raise CameraError('camera reports no ISO')

    def set_iso(self, value: int) -> None:
        st = self._text('/iso', {'value': value})
        if f'iso={value}' not in st:
            raise CameraError(f'ISO {value} not applied: {st.strip()}')

    def ensure_bulb(self) -> None:
        """Steps the shutter speed slower until the camera reports Bulb (65535/1)."""
        for _ in range(self.MAX_SHUTTER_STEPS):
            if self.status().get('bulb') == 'true':
                return
            self._text('/shutter', {'dir': 'slower'})
        if self.status().get('bulb') != 'true':
            raise CameraError('could not reach Bulb: is the mode dial on M?')

    def capture(self, ms: int) -> None:
        """Opens a Bulb exposure that the app closes after ms milliseconds. Returns at once."""
        reply = self._text('/capture', {'ms': ms, 'method': 'burstable'}).strip()
        if not reply.startswith('BULB exposing'):
            raise CameraError(f'capture refused: {reply}')

    def files(self) -> list[tuple[str, int]]:
        """DCIM files, newest first: [("100MSDCF/DSC04081.ARW", 16318464), ...]."""
        out = []
        for line in self._text('/files').splitlines():
            name, _, size = line.rpartition(' ')
            if name:
                try:
                    out.append((name, int(size)))
                except ValueError:
                    pass
        return out

    def newest_arw(self) -> tuple[str, int] | None:
        for name, size in self.files():
            if name.upper().endswith('.ARW'):
                return name, size
        return None

    def wait_new_arw(self, previous: str | None, timeout: float) -> str:
        """Waits for an ARW newer than previous whose size has stopped changing; returns its name."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            cur = self.newest_arw()
            if cur and cur[0] != previous:
                if last == cur:             # same size twice in a row: written
                    return cur[0]
                last = cur
            time.sleep(1.0)
        raise CameraError(f'no new ARW on the card {timeout:.0f} s after the exposure')

    def download(self, name: str) -> bytes:
        """One DCIM file (~16 MB ARW, ~13 s over the camera's Wi-Fi)."""
        return self._get('/dcim/' + name, timeout=120)

    # --- focus (camera-app FocusControl) --------------------------------------------------------

    @staticmethod
    def _focus_state(text: str) -> dict:
        """The focus_* lines of a reply, without the prefix: armed, offset, moving, min, max, mode, last."""
        out = {}
        for line in text.splitlines():
            k, sep, v = line.partition('=')
            if sep and k.startswith('focus_'):
                out[k[len('focus_'):]] = v.strip()
        return out

    def focus(self) -> dict:
        return self._focus_state(self._text('/focus'))

    def focus_arm(self, mode: str = '') -> dict:
        """Autofocus in `mode` (auto, dmf, manual; '' = current): arms the offsets, current position = 0."""
        text = self._get('/focusarm', {'mode': mode} if mode else None, timeout=15).decode('utf-8', 'replace')
        st = self._focus_state(text)
        if st.get('armed') != 'true':
            raise CameraError(f'focus not armed: {text.splitlines()[0] if text else "?"}')
        return st

    def focus_mode(self, mode: str) -> dict:
        """Sets the focus mode (auto, dmf, manual) without an autofocus."""
        st = self._focus_state(self._text('/focusmode', {'value': mode}))
        if st.get('mode') != mode:
            raise CameraError(f'focus mode {mode} not applied: {st.get("last", "?")}')
        return st

    def focus_move(self, offset: int) -> dict:
        """Moves the lens to `offset` (-16..16 from the reference) and waits; raises unless accepted."""
        text = self._get('/focus', {'offset': offset}, timeout=15).decode('utf-8', 'replace')
        first = text.splitlines()[0] if text else ''
        st = self._focus_state(text)
        if not first.startswith(f'shift({offset}) -> true') or st.get('offset') != str(offset):
            raise CameraError(f'focus move to {offset} failed: {first}')
        return st
