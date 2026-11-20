"""The Dashboard: its JSON route (/dashboard/status) and its page on the root, against the fake camera-app."""
import json
import socket
import time
import urllib.request

import pytest

from conftest import SERVER_DIR

MANIFEST = SERVER_DIR.parent / '.release-please-manifest.json'
SERVER_VERSION = json.loads(MANIFEST.read_text(encoding='utf-8'))['.']


def get(alpaca, path: str) -> tuple[str, bytes]:
    with urllib.request.urlopen(alpaca.base + path, timeout=10) as r:
        return r.headers.get('Content-Type', ''), r.read()


def status(alpaca) -> dict:
    content_type, body = get(alpaca, '/dashboard/status')
    assert content_type.startswith('application/json')
    return json.loads(body)


def test_reports_camera_app_reachable_and_both_versions(alpaca):
    st = status(alpaca)
    assert st['server']['version'] == SERVER_VERSION
    assert st['camera_app']['reachable'] is True
    assert st['camera_app']['version'] == SERVER_VERSION
    assert st['version_mismatch'] is False


def test_stopping_camera_app_turns_it_not_reachable_within_2_s(alpaca, camera_app):
    # The page polls every 2 s: not Reachable on the page within 2 to 4 s.
    assert status(alpaca)['camera_app']['reachable'] is True
    camera_app.stop()
    t0 = time.monotonic()
    while status(alpaca)['camera_app']['reachable']:
        assert time.monotonic() - t0 < 2, 'still Reachable'
        time.sleep(0.1)
    st = status(alpaca)
    assert st['camera_app']['version'] is None
    assert st['version_mismatch'] is False


def test_connecting_the_devices_turns_them_connected(alpaca):
    st = status(alpaca)
    assert st['camera']['connected'] is False
    assert st['focuser']['connected'] is False

    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.put('focuser', 'connected', Connected='true')['ErrorNumber'] == 0

    st = status(alpaca)
    assert st['camera'] == {'connected': True, 'state': 'IDLE', 'exposing': False}
    assert st['focuser'] == {'connected': True, 'armed': True, 'position': 16, 'moving': False}


def test_an_exposure_shows_in_progress(alpaca):
    alpaca.put('camera', 'connected', Connected='true')
    body = alpaca.put('camera', 'startexposure', Duration=1.0, Light='true')
    assert body['ErrorNumber'] == 0, body['ErrorMessage']
    assert status(alpaca)['camera']['exposing'] is True
    deadline = time.monotonic() + 15
    while not alpaca.get('camera', 'imageready'):
        assert time.monotonic() < deadline, 'no image'
        time.sleep(0.1)
    assert status(alpaca)['camera']['exposing'] is False


def test_a_different_camera_app_version_is_a_mismatch(alpaca, camera_app):
    camera_app.camera.version = '0.0.1-other'
    time.sleep(1.1)                                  # past the probe's cache
    st = status(alpaca)
    assert st['camera_app']['version'] == '0.0.1-other'
    assert st['version_mismatch'] is True


def test_root_page_is_the_dashboard_and_polls_the_json_route_by_a_relative_url(alpaca):
    content_type, body = get(alpaca, '/')
    page = body.decode('utf-8')
    assert content_type.startswith('text/html')
    assert '<title>' in page and 'Dashboard' in page
    assert "fetch('dashboard/status'" in page      # relative: works whatever address opened the page


def lan_address() -> str | None:
    """This machine's address on the local network (no packet is sent), or None without one."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith('127.') or ip == '0.0.0.0' else ip


def test_page_opens_from_the_local_network_with_the_default_address(camera_app, start_server):
    ip = lan_address()
    if ip is None:
        pytest.skip('no local network address')
    alpaca = start_server(camera_app.url, ip_address='')       # config-template.toml: any address
    with urllib.request.urlopen(f'http://{ip}:{alpaca.base.rsplit(":", 1)[1]}/', timeout=10) as r:
        assert b'Dashboard' in r.read()
