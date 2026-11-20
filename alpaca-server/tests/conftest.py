"""Test bench: the Alpaca Server runs as a real process (app.py --config ...) against a fake camera-app,
and the tests talk to it through the Alpaca API, as N.I.N.A. does."""
import json
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from fake_camera_app import FakeCameraApp

SERVER_DIR = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def write_config(path: Path, camera_url: str, port: int, location: str = 'Test bench',
                 ip_address: str = '127.0.0.1') -> Path:
    """A config.toml like the shipped one, for the sample ARW (64 x 40) and a local camera-app."""
    path.write_text(f"""
[network]
ip_address = '{ip_address}'
port = {port}

[server]
location = '{location}'
verbose_driver_exceptions = false

[device]
camera_url = '{camera_url}'
sensor_x = 64
sensor_y = 40
pixel_size_um = 4.8
max_adu = 16383
bayer_offset_x = 0
bayer_offset_y = 0
sensor_type = 'color'
exposure_min = 1.0
exposure_max = 3600.0
file_timeout = 10.0

[focuser]
arm_mode = 'manual'
drive_mode = 'auto'
arm_on_connect = true

[logging]
log_level = 'INFO'
log_to_stdout = false
max_size_mb = 5
num_keep_logs = 1
""")
    return path


class Alpaca:
    """Minimal Alpaca client: GET/PUT one member of one device, raising on HTTP errors."""

    def __init__(self, base: str):
        self.base = base
        self._tid = 0

    def _fields(self, fields: dict) -> dict:
        self._tid += 1
        return {**fields, 'ClientID': 1, 'ClientTransactionID': self._tid}

    def request(self, method: str, path: str, headers: dict | None = None, **fields):
        data = urllib.parse.urlencode(self._fields(fields))
        if method == 'GET':
            req = urllib.request.Request(f'{self.base}{path}?{data}', headers=headers or {})
        else:
            req = urllib.request.Request(f'{self.base}{path}', data=data.encode(), method='PUT',
                                         headers=headers or {})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.headers.get('Content-Type', ''), r.read()

    def call(self, method: str, path: str, **fields) -> dict:
        return json.loads(self.request(method, path, **fields)[1])

    def get(self, device: str, member: str, **fields):
        """Value of a property; fails the test on an Alpaca error."""
        body = self.call('GET', f'/api/v1/{device}/0/{member}', **fields)
        assert body['ErrorNumber'] == 0, body['ErrorMessage']
        return body['Value']

    def put(self, device: str, member: str, **fields) -> dict:
        return self.call('PUT', f'/api/v1/{device}/0/{member}', **fields)


class AlpacaServer:
    """app.py --config CONFIG, or app.py alone (configuration from the user folder) when use_option is False."""

    def __init__(self, config: Path, cwd: Path, use_option: bool = True, env: dict | None = None):
        self.port = int(next(line.split('=')[1] for line in config.read_text().splitlines()
                             if line.startswith('port')))
        option = ['--config', str(config)] if use_option else []
        self.proc = subprocess.Popen([sys.executable, str(SERVER_DIR / 'app.py'), *option],
                                     cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.client = Alpaca(f'http://127.0.0.1:{self.port}')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f'Alpaca Server exited: {self.proc.stderr.read().decode()}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError('Alpaca Server did not start')

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def camera_app():
    app = FakeCameraApp().start()
    yield app
    app.stop()


@pytest.fixture
def start_server(tmp_path):
    """start_server(camera_url, **config) -> Alpaca client of a server started with --config."""
    servers = []

    def start(camera_url: str, **kw) -> Alpaca:
        config = write_config(tmp_path / 'test-config.toml', camera_url, free_port(), **kw)
        servers.append(AlpacaServer(config, tmp_path))
        return servers[-1].client

    yield start
    for s in servers:
        s.stop()


@pytest.fixture
def alpaca(camera_app, start_server) -> Alpaca:
    return start_server(camera_app.url)
