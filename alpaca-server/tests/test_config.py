"""The configuration loads from an explicit path; without one, from config.toml next to app.py."""
import subprocess
import sys

from conftest import SERVER_DIR


def test_server_uses_the_config_given_on_the_command_line(alpaca):
    desc = alpaca.call('GET', '/management/v1/description')['Value']
    assert desc['Location'] == 'Test bench'


def test_default_config_is_config_toml_next_to_the_script():
    out = subprocess.run(
        [sys.executable, '-c', f'import sys; sys.path.insert(0, {str(SERVER_DIR)!r}); import config; '
                               'print(config.Config.port, config.Config.location)'],
        cwd='/', capture_output=True, text=True, check=True).stdout
    assert out.split() == ['11111', 'Home']
