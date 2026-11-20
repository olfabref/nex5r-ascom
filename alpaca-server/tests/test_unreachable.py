"""camera-app not Reachable: Connect fails with a clean Alpaca error, not an HTTP error or a hang."""
from conftest import free_port


def test_connect_without_camera_app_gives_an_alpaca_error(start_server):
    alpaca = start_server(f'http://127.0.0.1:{free_port()}')     # nothing listens there
    body = alpaca.put('camera', 'connected', Connected='true')
    assert body['ErrorNumber'] == 0x500
    assert 'GET /status failed' in body['ErrorMessage']
    assert alpaca.get('camera', 'connected') is False
