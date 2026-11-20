"""End-to-end check of the Update from the Dashboard, run in CI on a Windows runner after check_install.py
(never on a user's machine: it edits the configuration in %APPDATA% and uninstalls at the end).

    python alpaca-server/installer/check_update.py OLD_SETUP NEW_SETUP NEW_VERSION

OLD_SETUP and NEW_SETUP are two installers of the same code, NEW_SETUP built with the newer NEW_VERSION.
No real Release is involved: tests/fake_github.py serves a fake latest Release vNEW_VERSION, with
NEW_SETUP and a SHA256SUMS, on 127.0.0.1 (NEX5R_RELEASES_URL, inherited by the installed server).

1. silent install of OLD_SETUP: the server answers with its Version;
2. Update with a wrong SHA-256 in SHA256SUMS: cancelled with an explicit message, the server keeps running;
3. Update with the right SHA256SUMS: the server quits, the installer runs, and the new server answers with
   NEW_VERSION and the configuration edited before the Update (so it restarted and the configuration is kept);
4. silent uninstall.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import check_install as ci

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tests'))
from fake_github import INSTALLER, FakeGitHub, sha256sums  # noqa: E402

LOCATION = 'Kept across the Update'


def dashboard_status() -> dict | None:
    try:
        with urllib.request.urlopen(f'{ci.SERVER}/dashboard/status', timeout=5) as r:
            return json.loads(r.read())
    except OSError:
        return None


def start_update() -> tuple[int, dict]:
    req = urllib.request.Request(f'{ci.SERVER}/dashboard/action/update', method='POST',
                                 data=json.dumps({'confirmed': True}).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def update_state() -> dict:
    return (dashboard_status() or {}).get('update') or {}


def main(old_setup: Path, new_setup: Path, new_version: str):
    github = FakeGitHub(f'v{new_version}', assets={
        INSTALLER: new_setup,
        'SHA256SUMS': sha256sums({INSTALLER: b'not the installer'}),
    }).start()
    os.environ['NEX5R_RELEASES_URL'] = github.url      # inherited by the installer, then the server
    try:
        ci.step(f'silent install of {old_setup.name}')
        ci.run_installer(old_setup, 'update-old-install')
        ci.wait_for('the server answers the management API', lambda: ci.description() is not None)
        old_version = ci.description()['Version']
        print(f'installed Version {old_version}, fake latest Release v{new_version}')
        assert old_version != new_version
        st = dashboard_status()
        assert st['update']['installable'] is True, st['update']
        ci.wait_for('the Release check finds the fake Release',
                    lambda: (dashboard_status() or {}).get('release', {}).get('latest') == new_version)

        # Edited while the old server runs: only a restarted server can report it.
        text = ci.CONFIG.read_text(encoding='utf-8')
        text, n = re.subn(r"^location = '[^']*'", f"location = '{LOCATION}'", text, flags=re.M)
        assert n == 1, 'no location in config.toml'
        ci.CONFIG.write_text(text, encoding='utf-8')

        ci.step('Update with a wrong SHA-256')
        code, reply = start_update()
        print(code, reply)
        assert code == 200 and reply['ok'], reply
        ci.wait_for('the Update is cancelled', lambda: update_state().get('state') == 'failed', timeout=120)
        message = update_state()['message']
        print(message)
        assert 'wrong SHA-256' in message and f'keeps running Version {old_version}' in message, message
        time.sleep(3)
        assert (ci.description() or {}).get('Version') == old_version, 'the server stopped'

        ci.step('Update with the right SHA-256')
        github.assets['SHA256SUMS'] = sha256sums({INSTALLER: new_setup})
        code, reply = start_update()
        print(code, reply)
        assert code == 200 and reply['ok'], reply
        ci.wait_for(f'the server answers with Version {new_version}',
                    lambda: (ci.description() or {}).get('Version') == new_version, timeout=300)
        desc = ci.description()
        print(desc)
        assert desc['Location'] == LOCATION, desc
        st = dashboard_status()
        assert st['server']['version'] == new_version and st['update']['state'] == 'idle', st
        assert st['release']['update_available'] is False, st['release']
        assert ci.EXE.is_file() and ci.STARTUP.is_file()
        print('downloads:', github.downloads())

        ci.step('silent uninstall')
        ci.subprocess.run([str(ci.APP_DIR / 'unins000.exe'), *ci.SILENT,
                           f'/LOG={ci.LOG_DIR / "update-uninstall.log"}'], timeout=300, check=True)
        ci.wait_for('the installed files are removed', lambda: not ci.EXE.exists())
        ci.wait_for('the server is stopped', lambda: ci.description() is None, timeout=10)
        ci.step('OK')
    except BaseException:
        dump_logs()
        raise
    finally:
        github.stop()


def dump_logs():
    """The server's log and the Update's installer log, to see why it failed."""
    for log in [ci.APP_DIR / 'alpyca.log',
                *Path(os.environ['TEMP']).glob('nex5r-ascom-update-*/install.log')]:
        if log.is_file():
            print(f'---- {log}')
            print(log.read_text(encoding='utf-8', errors='replace')[-20000:])


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3])
