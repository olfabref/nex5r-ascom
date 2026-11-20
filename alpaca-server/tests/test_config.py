"""The configuration: an explicit path (--config), otherwise config.toml in the user folder,
created from the template shipped with the code on first launch (ADR 0002)."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import SERVER_DIR, AlpacaServer, free_port, write_config

TEMPLATE = SERVER_DIR / 'config-template.toml'


def test_server_uses_the_config_given_on_the_command_line(alpaca):
    desc = alpaca.call('GET', '/management/v1/description')['Value']
    assert desc['Location'] == 'Test bench'


@pytest.fixture
def user_home(tmp_path):
    """A temporary user folder: every variable the OSes use to locate it points into tmp_path."""
    home = tmp_path / 'home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
           'APPDATA': str(home / 'AppData' / 'Roaming'), 'XDG_CONFIG_HOME': str(home / '.config')}
    return home, env


def user_config(home: Path) -> Path:
    """Where the configuration lives: %APPDATA% on Windows, ~/Library/Application Support on Mac."""
    if sys.platform == 'win32':
        base = home / 'AppData' / 'Roaming'
    elif sys.platform == 'darwin':
        base = home / 'Library' / 'Application Support'
    else:
        base = home / '.config'
    return base / 'nex5r-ascom' / 'config.toml'


def test_first_launch_creates_the_user_config_from_the_template(user_home, tmp_path):
    home, env = user_home
    proc = subprocess.Popen([sys.executable, str(SERVER_DIR / 'app.py')], cwd=tmp_path, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not user_config(home).exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.1)
        assert user_config(home).read_bytes() == TEMPLATE.read_bytes()
    finally:
        proc.terminate()
        proc.wait(5)


def test_later_launches_keep_and_use_a_hand_edited_value(user_home, tmp_path, camera_app):
    home, env = user_home
    config = user_config(home)
    config.parent.mkdir(parents=True)
    write_config(config, camera_app.url, free_port(), location='Edited by hand')
    server = AlpacaServer(config, tmp_path, use_option=False, env=env)
    try:
        desc = server.client.call('GET', '/management/v1/description')['Value']
        assert desc['Location'] == 'Edited by hand'
    finally:
        server.stop()
    assert "location = 'Edited by hand'" in config.read_text()
