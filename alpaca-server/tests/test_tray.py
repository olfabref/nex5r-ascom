"""The tray icon (Windows system tray, Mac menu bar): it shows that the Alpaca Server is running, opens
the Dashboard and quits the server. The real server process runs against a fake pystray
(tests/fake_tray) that records what the tray shows and clicks its menu entries."""
import json
import os
import time
from pathlib import Path

import pytest

from conftest import AlpacaServer, free_port, write_config
from fake_github import FakeGitHub

FAKE_TRAY = Path(__file__).resolve().parent / 'fake_tray'


def wait_for(condition, timeout: float = 10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError('timed out')


class Tray:
    """The fake tray of one server process: what it shows, and clicks on its menu."""

    def __init__(self, folder: Path):
        self.folder = folder

    def shown(self) -> dict | None:
        try:
            return json.loads((self.folder / 'tray.json').read_text())
        except (OSError, ValueError):
            return None

    def click(self, text: str):
        (self.folder / 'click').write_text(text)

    def opened(self) -> list[str]:
        path = self.folder / 'opened'
        return path.read_text().split() if path.exists() else []


@pytest.fixture
def tray_server(tmp_path, camera_app):
    """tray_server(tray=True, fail=False, releases_url=None) -> (AlpacaServer, Tray)."""
    servers = []

    def start(tray: bool = True, fail: bool = False, releases_url: str | None = None):
        folder = tmp_path / f'tray{len(servers)}'
        folder.mkdir()
        port = free_port()
        config = write_config(tmp_path / f'config{len(servers)}.toml', camera_app.url, port)
        env = {**os.environ, 'FAKE_TRAY_DIR': str(folder),
               'PYTHONPATH': os.pathsep.join([str(FAKE_TRAY), os.environ.get('PYTHONPATH', '')])}
        if fail:
            env['FAKE_TRAY_FAIL'] = '1'
        if releases_url:
            env['NEX5R_RELEASES_URL'] = releases_url
        servers.append(AlpacaServer(config, tmp_path, env=env, tray=tray))
        return servers[-1], Tray(folder)

    yield start
    for s in servers:
        s.stop()


def test_quit_in_the_tray_stops_the_server(tray_server):
    server, tray = tray_server()
    assert server.client.get('camera', 'connected') is False
    wait_for(lambda: 'Quit' in (tray.shown() or {}).get('menu', []))
    tray.click('Quit')
    assert server.proc.wait(10) == 0


def test_open_in_the_tray_opens_the_dashboard(tray_server):
    server, tray = tray_server()
    shown = wait_for(tray.shown)
    assert shown['default'] == ['Open Dashboard']       # double-click on the Windows icon
    tray.click('Open Dashboard')
    url = wait_for(tray.opened)[0]
    assert url == f'http://127.0.0.1:{server.port}/'     # ip_address '' or 127.0.0.1: this machine


def test_the_tray_shows_that_the_server_runs_and_its_version(tray_server):
    server, tray = tray_server()
    version = server.client.call('GET', '/management/v1/description')['Value']['Version']
    shown = wait_for(tray.shown)
    assert f'Alpaca Server {version}: running' in shown['title']
    assert f'Alpaca Server {version}: running' in shown['menu']
    assert not any('available' in entry for entry in shown['menu'])


def test_the_tray_flags_a_new_release(tray_server):
    github = FakeGitHub(release='v99.0.0').start()
    try:
        server, tray = tray_server(releases_url=github.url)
        shown = wait_for(lambda: (s := tray.shown()) and 'Version 99.0.0 available' in s['menu'] and s)
        assert 'Version 99.0.0 available' in shown['title']
        tray.click('Version 99.0.0 available')           # the Update starts from the Dashboard
        assert wait_for(tray.opened) == [f'http://127.0.0.1:{server.port}/']
    finally:
        github.stop()


def test_no_tray_option_runs_the_server_without_the_icon(tray_server):
    server, tray = tray_server(tray=False)
    assert server.client.get('camera', 'connected') is False
    time.sleep(0.5)
    assert tray.shown() is None


def test_the_server_runs_when_no_tray_can_be_shown(tray_server):
    server, tray = tray_server(fail=True)
    assert server.client.get('camera', 'connected') is False
    time.sleep(0.5)
    assert server.proc.poll() is None
    assert server.client.get('camera', 'connected') is False
