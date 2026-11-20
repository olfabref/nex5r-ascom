"""The Alpaca Server starts without waiting on name resolution: on some networks (GitHub macOS runners)
a reverse lookup of the bound address hangs for tens of seconds."""
import os
import time

from conftest import AlpacaServer, free_port, write_config

HANGING_REVERSE_LOOKUP = """
import socket, time
def _hang(addr):
    time.sleep(60)
    raise socket.herror(1, 'Unknown host')
socket.gethostbyaddr = _hang
"""


def test_server_starts_when_reverse_dns_hangs(tmp_path):
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'sitecustomize.py').write_text(HANGING_REVERSE_LOOKUP)
    env = {**os.environ, 'PYTHONPATH': str(site)}
    config = write_config(tmp_path / 'test-config.toml', f'http://127.0.0.1:{free_port()}', free_port())
    started = time.monotonic()
    server = AlpacaServer(config, tmp_path, env=env)
    try:
        assert time.monotonic() - started < 10
        assert server.client.get('camera', 'connected') is False
    finally:
        server.stop()
