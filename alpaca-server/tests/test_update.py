"""The Update (ADR 0002): download the newer Release's installer, check its SHA-256 against SHA256SUMS, run
it silently and quit; from the sources, only show the git command. GitHub is mocked (tests/fake_github.py);
the installer launch and the quit are recorded instead of run (in-process tests), or the request is made
through the Dashboard of a real server (sources)."""
import hashlib

import pytest

import update
from fake_github import INSTALLER, FakeGitHub, sha256sums
from test_dashboard import action, get, status

SETUP = b'MZ fake installer of v99.0.0'


@pytest.fixture
def github():
    fake = FakeGitHub('v99.0.0', assets={INSTALLER: SETUP, 'SHA256SUMS': sha256sums({INSTALLER: SETUP})}).start()
    yield fake
    fake.stop()


class Recorder:
    """Stands for the OS: the installer launches and the server quits."""

    def __init__(self):
        self.launched: list[tuple[bytes, list[str]]] = []
        self.quits = 0

    def launch(self, exe, args):
        self.launched.append((exe.read_bytes(), list(args)))

    def quit(self):
        self.quits += 1


def updater(github, rec, tmp_path, installable=True, current='0.1.0') -> update.Updater:
    return update.Updater(current=current, url=github.url, installable=installable,
                          launch=rec.launch, quit=rec.quit, workdir=tmp_path)


def test_a_checked_installer_is_run_silently_then_the_server_quits(github, tmp_path):
    rec = Recorder()
    up = updater(github, rec, tmp_path)
    message = up.start()
    assert '99.0.0' in message
    up.wait()
    assert up.state()['state'] == 'installing', up.state()
    assert sorted(github.downloads()) == ['SHA256SUMS', INSTALLER]
    [(exe, args)] = rec.launched
    assert exe == SETUP
    assert args[:3] == ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
    assert rec.quits == 1


def test_a_wrong_sha256_cancels_the_update_and_the_server_keeps_running(github, tmp_path):
    github.assets['SHA256SUMS'] = sha256sums({INSTALLER: b'another installer'})
    rec = Recorder()
    up = updater(github, rec, tmp_path)
    up.start()
    up.wait()
    st = up.state()
    assert st['state'] == 'failed'
    assert 'wrong SHA-256' in st['message'] and hashlib.sha256(SETUP).hexdigest() in st['message']
    assert 'keeps running Version 0.1.0' in st['message']
    assert rec.launched == [] and rec.quits == 0
    assert not (tmp_path / INSTALLER).exists()        # never left where it could be run


def test_sha256sums_without_the_installer_cancels_the_update(github, tmp_path):
    github.assets['SHA256SUMS'] = sha256sums({'nex5r.apk': b'apk'})
    rec = Recorder()
    up = updater(github, rec, tmp_path)
    up.start()
    up.wait()
    assert up.state()['state'] == 'failed'
    assert 'no line for nex5r-ascom-setup.exe' in up.state()['message']
    assert rec.launched == [] and rec.quits == 0


def test_an_update_can_be_retried_after_a_failure(github, tmp_path):
    good = github.assets['SHA256SUMS']
    github.assets['SHA256SUMS'] = b'0' * 64 + b'  ' + INSTALLER.encode()
    rec = Recorder()
    up = updater(github, rec, tmp_path)
    up.start()
    up.wait()
    assert up.state()['state'] == 'failed'
    github.assets['SHA256SUMS'] = good
    up.start()
    up.wait()
    assert up.state()['state'] == 'installing'
    assert len(rec.launched) == 1 and rec.quits == 1


@pytest.mark.parametrize('current', ['99.0.0', '99.1.0'], ids=['same Version', 'newer Version'])
def test_no_newer_release_is_refused(github, tmp_path, current):
    rec = Recorder()
    with pytest.raises(update.Refused, match='up to date'):
        updater(github, rec, tmp_path, current=current).start()
    assert github.downloads() == [] and rec.launched == []


def test_offline_is_refused(tmp_path):
    rec = Recorder()
    up = update.Updater(current='0.1.0', url='http://127.0.0.1:9/releases/latest', installable=True,
                        launch=rec.launch, quit=rec.quit, workdir=tmp_path)
    with pytest.raises(update.Refused, match='Cannot look up the latest Release'):
        up.start()


def test_from_the_sources_only_the_git_command_is_shown(github, tmp_path):
    rec = Recorder()
    up = updater(github, rec, tmp_path, installable=False)
    message = up.start()
    assert 'git -C' in message and 'pull' in message and 'nothing was run' in message
    assert up.state()['command'] == update.sources_command()
    assert up.state()['state'] == 'idle'
    assert github.paths == [] and rec.launched == [] and rec.quits == 0


# Through the Dashboard of a real server, run from the sources (as on Mac and in CI).

@pytest.fixture
def server(camera_app, start_server, github):
    return start_server(camera_app.url, releases_url=github.url)


def test_from_the_sources_the_dashboard_shows_the_git_command_and_runs_nothing(server, github):
    code, reply = action(server, 'update', confirmed=True)
    assert code == 200, reply
    assert reply['ok'] is True
    assert 'git -C' in reply['message'] and 'pull' in reply['message'] and 'nothing was run' in reply['message']
    assert github.downloads() == []
    st = status(server)['update']
    assert st['installable'] is False and st['state'] == 'idle'
    assert 'pull' in st['command']
    assert status(server)['server']['version']        # still serving


@pytest.mark.parametrize('device', ['camera', 'focuser'])
def test_update_is_refused_while_a_device_is_connected(server, github, device):
    assert server.put(device, 'connected', Connected='true')['ErrorNumber'] == 0
    code, reply = action(server, 'update', confirmed=True)
    assert code == 409
    assert reply['ok'] is False and 'Connected' in reply['message']
    assert github.downloads() == []


def test_update_needs_a_confirmation(server):
    assert action(server, 'update')[0] == 400


def test_the_page_has_an_update_button_and_reloads_after_the_update(server):
    page = get(server, '/')[1].decode('utf-8')
    assert "button('update'" in page
    assert 'update: s =>' in page                     # a renderer for the section
    assert 'Update in progress' in page and 'location.reload()' in page
