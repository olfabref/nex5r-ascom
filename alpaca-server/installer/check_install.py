"""End-to-end check of the Windows installer, run in CI on a Windows runner (never on a user's machine:
it edits the configuration in %APPDATA% and uninstalls at the end).

    python alpaca-server/installer/check_install.py alpaca-server/dist/nex5r-ascom-setup.exe [VERSION]

1. silent install: the server starts and answers the Alpaca management API with VERSION
   (default: the Version of alpaca-server/version.py);
   start at login is in place; config.toml is created in the user folder;
2. reinstall on top, silently, while the server runs: the server restarts and the configuration is kept;
3. silent uninstall: the server is stopped, start at login and the installed files are gone.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVER = 'http://127.0.0.1:11111'
SILENT = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
APP_DIR = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'nex5r-ascom'
EXE = APP_DIR / 'nex5r-ascom.exe'
STARTUP = (Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
           / 'nex5r-ascom Alpaca Server.lnk')
CONFIG = Path(os.environ['APPDATA']) / 'nex5r-ascom' / 'config.toml'
LOG_DIR = Path(os.environ.get('RUNNER_TEMP', os.environ['TEMP']))


def step(text: str):
    print(f'== {text}', flush=True)


def wait_for(what: str, condition, timeout: float = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.5)
    raise SystemExit(f'FAILED: {what} (after {timeout:.0f} s)')


def description() -> dict | None:
    try:
        with urllib.request.urlopen(f'{SERVER}/management/v1/description', timeout=2) as r:
            return json.loads(r.read())['Value']
    except OSError:
        return None


def run_installer(setup: Path, name: str):
    log = LOG_DIR / f'{name}.log'
    code = subprocess.run([str(setup), *SILENT, f'/LOG={log}'], timeout=300).returncode
    if code:
        print(log.read_text(encoding='utf-8', errors='replace'))
        raise SystemExit(f'FAILED: {name} exited with {code}')


def main(setup: Path, version: str):
    assert not CONFIG.exists(), f'{CONFIG} already exists: run on a clean runner'

    step('silent install')
    run_installer(setup, 'install')
    assert EXE.is_file(), EXE
    assert STARTUP.is_file(), f'no start at login: {STARTUP}'
    wait_for('the server answers the management API', lambda: description() is not None)
    desc = description()
    print(desc)
    assert desc['Version'] == version, desc
    assert CONFIG.is_file(), f'no configuration in the user folder: {CONFIG}'

    step('reinstall on top, the server running')
    text = CONFIG.read_text(encoding='utf-8')
    assert "location = 'Home'" in text
    CONFIG.write_text(text.replace("location = 'Home'", "location = 'Kept across reinstall'"),
                      encoding='utf-8')
    run_installer(setup, 'reinstall')
    # The server that was running read 'Home': this Location proves a restart and a kept configuration
    wait_for('the reinstalled server answers with the kept configuration',
             lambda: (description() or {}).get('Location') == 'Kept across reinstall')
    assert "location = 'Kept across reinstall'" in CONFIG.read_text(encoding='utf-8')
    assert STARTUP.is_file()

    step('silent uninstall')
    # unins000.exe relaunches itself from %TEMP% and returns at once: wait for its effects
    subprocess.run([str(APP_DIR / 'unins000.exe'), *SILENT, f'/LOG={LOG_DIR / "uninstall.log"}'],
                   timeout=300, check=True)
    wait_for('the installed files are removed', lambda: not EXE.exists())
    wait_for('start at login is removed', lambda: not STARTUP.exists())
    wait_for('the server is stopped', lambda: description() is None, timeout=10)
    assert CONFIG.is_file(), 'the uninstaller removed the configuration'
    step('OK')


def source_version() -> str:
    """The Version of version.py next to this script (the one build.ps1 gives the installer)."""
    text = (Path(__file__).resolve().parent.parent / 'version.py').read_text(encoding='utf-8')
    return text.split("__version__ = '", 1)[1].split("'", 1)[0]


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(), sys.argv[2] if len(sys.argv) > 2 else source_version())
