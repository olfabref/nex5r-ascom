"""A fake camera-app: the HTTP routes the Alpaca Server uses (see camera-app HttpServer.java), with the
same plain-text replies, backed by a little state machine instead of the Camera.

Each Bulb exposure (/capture?ms=N) writes tests/data/sample.ARW to the fake card N ms later.
"""
import socketserver
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SAMPLE_ARW = (Path(__file__).parent / 'data' / 'sample.ARW').read_bytes()

# Shutter speeds from 30" to Bulb, as the camera steps them with /shutter?dir=slower.
SHUTTER_SPEEDS = ['10/1', '13/1', '15/1', '20/1', '25/1', '30/1', '65535/1']
ISOS = [0, 100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600]
FOCUS_MODES = ('auto', 'dmf', 'manual')


class FakeCamera:
    """State of the fake Camera; every method returns the reply body."""

    def __init__(self):
        self._lock = threading.Lock()
        self.shutter_index = 0
        self.iso = 100
        self.exposing = False
        self.last = '-'
        self.files = {'100MSDCF/DSC00001.ARW': SAMPLE_ARW}     # an older shot already on the card
        self.next_number = 2
        self.focus_armed = False
        self.focus_offset = 0
        self.focus_mode = 'manual'
        self.focus_last = '-'

    @property
    def shutter(self) -> str:
        return SHUTTER_SPEEDS[self.shutter_index]

    def bulb_state(self) -> str:
        bulb = str(self.shutter == '65535/1').lower()
        return (f'shutter={self.shutter}\nbulb={bulb}\nexposing={str(self.exposing).lower()}\n'
                f'iso={self.iso}\nisos={",".join(map(str, ISOS))}\ninhibition=-\nlast={self.last}\n')

    def focus_state(self) -> str:
        return (f'focus_armed={str(self.focus_armed).lower()}\nfocus_offset={self.focus_offset}\n'
                f'focus_moving=false\nfocus_min=-16\nfocus_max=16\nfocus_mode={self.focus_mode}\n'
                f'focus_last={self.focus_last}\n')

    def status(self) -> str:
        return 'ip=127.0.0.1\n' + self.bulb_state() + self.focus_state()

    def step_shutter(self, slower: bool) -> str:
        with self._lock:
            step = 1 if slower else -1
            self.shutter_index = min(max(self.shutter_index + step, 0), len(SHUTTER_SPEEDS) - 1)
        return self.bulb_state()

    def set_iso(self, value: int) -> str:
        if value in ISOS:
            self.iso = value
        return self.bulb_state()

    def capture(self, ms: int) -> str:
        with self._lock:
            if self.shutter != '65535/1':
                return f'NOT BULB: shutter {self.shutter}, duration ignored'
            if self.exposing:
                return 'busy: exposure running'
            self.exposing = True
            self.last = f'BULB exposing {ms / 1000.0} s (burstable)'
        threading.Timer(ms / 1000.0, self._end_exposure).start()
        return self.last

    def _end_exposure(self):
        with self._lock:
            self.files[f'100MSDCF/DSC{self.next_number:05d}.ARW'] = SAMPLE_ARW
            self.next_number += 1
            self.exposing = False

    def list_files(self) -> str:
        return ''.join(f'{name} {len(data)}\n' for name, data in sorted(self.files.items(), reverse=True))

    def focus_arm(self, mode: str) -> str:
        if mode:
            self.focus_mode = mode
        self.focus_armed = True
        self.focus_offset = 0
        self.focus_last = f'armed: autofocus in {self.focus_mode}, done'
        return self.focus_last + '\n' + self.focus_state()

    def set_focus_mode(self, mode: str) -> str:
        self.focus_mode = mode
        self.focus_last = f'focus-mode -> {mode}'
        return self.focus_last + '\n' + self.focus_state()

    def focus_move(self, offset: int) -> str:
        if not self.focus_armed:
            self.focus_last = 'not armed: call /focusarm first'
        else:
            time.sleep(0.05)
            self.focus_offset = offset
            self.focus_last = f'shift({offset}) -> true in 50 ms'
        return self.focus_last + '\n' + self.focus_state()


class _Handler(BaseHTTPRequestHandler):
    camera: FakeCamera = None

    def log_message(self, format, *args):
        pass

    def _reply(self, code: int, body, content_type='text/plain; charset=utf-8'):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        cam = self.camera
        if path == '/status':
            return self._reply(200, cam.status())
        if path == '/shutter' and q.get('dir') in ('slower', 'faster'):
            return self._reply(200, cam.step_shutter(q['dir'] == 'slower'))
        if path == '/iso':
            return self._reply(200, cam.set_iso(int(q['value'])) if 'value' in q else cam.status())
        if path == '/capture' and 'ms' in q:
            return self._reply(200, cam.capture(int(q['ms'])) + '\n')
        if path == '/files':
            return self._reply(200, cam.list_files())
        if path.startswith('/dcim/'):
            data = cam.files.get(path[len('/dcim/'):])
            if data is None:
                return self._reply(404, 'no such file\n')
            return self._reply(200, data, 'application/octet-stream')
        if path == '/focus':
            return self._reply(200, cam.focus_move(int(q['offset'])) if 'offset' in q else cam.focus_state())
        if path == '/focusarm' and q.get('mode', '') in ('',) + FOCUS_MODES:
            return self._reply(200, cam.focus_arm(q.get('mode', '')))
        if path == '/focusmode' and q.get('value') in FOCUS_MODES:
            return self._reply(200, cam.set_focus_mode(q['value']))
        return self._reply(404 if path not in ('/shutter', '/capture', '/focusarm', '/focusmode') else 400,
                           'not found\n')


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer without its socket.getfqdn() at bind, which can hang (GitHub macOS runners)."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class FakeCameraApp:
    """Serves a FakeCamera on 127.0.0.1, on a free port, in a background thread."""

    def __init__(self):
        self.camera = FakeCamera()
        handler = type('Handler', (_Handler,), {'camera': self.camera})
        self._httpd = _Server(('127.0.0.1', 0), handler)
        self._httpd.daemon_threads = True
        self.url = f'http://127.0.0.1:{self._httpd.server_address[1]}'
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
