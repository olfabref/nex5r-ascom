"""New Release detection: the Alpaca Server asks GitHub for the latest Release at startup, then every 6 h,
and the Dashboard shows whether a newer Version exists. GitHub is mocked (tests/fake_github.py)."""
import json
import time

import pytest

import release
from conftest import NO_GITHUB, SERVER_DIR
from fake_github import FakeGitHub
from test_dashboard import get, status

SERVER_VERSION = json.loads((SERVER_DIR.parent / '.release-please-manifest.json').read_text(encoding='utf-8'))['.']


@pytest.fixture
def github():
    fake = FakeGitHub().start()
    yield fake
    fake.stop()


def release_status(alpaca, until=lambda r: r['state'] != 'checking', timeout: float = 5) -> dict:
    """The Dashboard's release section, once the startup check is over."""
    deadline = time.monotonic() + timeout
    while not until(rel := status(alpaca)['release']):
        assert time.monotonic() < deadline, rel
        time.sleep(0.05)
    return rel


def test_a_newer_release_is_shown(camera_app, start_server, github):
    github.release = 'v99.1.0'
    alpaca = start_server(camera_app.url, releases_url=github.url)
    rel = release_status(alpaca)
    assert rel['state'] == 'available'
    assert rel['update_available'] is True
    assert rel['latest'] == '99.1.0'
    assert rel['url'] == 'https://github.com/olfabref/nex5r-ascom/releases/tag/v99.1.0'


@pytest.mark.parametrize('tag', [f'v{SERVER_VERSION}', None], ids=['same Version', 'no Release yet'])
def test_no_newer_release_is_up_to_date(camera_app, start_server, github, tag):
    github.release = tag
    alpaca = start_server(camera_app.url, releases_url=github.url)
    rel = release_status(alpaca)
    assert rel['state'] == 'up_to_date'
    assert rel['update_available'] is False
    assert rel['current'] == SERVER_VERSION


def test_without_network_it_cannot_check_and_the_server_carries_on(alpaca):
    # conftest's default releases URL is a closed port: like a mini-PC offline in the field.
    rel = release_status(alpaca)
    assert rel['state'] == 'cannot_check'
    assert rel['update_available'] is False and rel['latest'] is None
    assert rel['error']
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.get('camera', 'connected') is True


def test_the_github_request_names_the_client(camera_app, start_server, github):
    # GitHub's API refuses requests without a User-Agent.
    github.release = 'v99.1.0'
    alpaca = start_server(camera_app.url, releases_url=github.url)
    release_status(alpaca)
    headers = {k.lower(): v for k, v in github.requests[0].items()}
    assert headers['user-agent'].startswith('nex5r-ascom/')
    assert headers['accept'] == 'application/vnd.github+json'


def test_the_dashboard_page_renders_every_release_state(alpaca):
    page = get(alpaca, '/')[1].decode('utf-8')
    assert 'release: s =>' in page                                  # a renderer for the section
    for state, text in [('checking', 'checking'), ('available', 'available'),
                        ('up_to_date', 'up to date'), ('cannot_check', 'cannot check')]:
        assert f"{state}: s =>" in page and text in page


# In-process: the lookup the Update reuses, and the periodic check the tray icon follows.

def test_latest_release_lists_its_assets_for_the_update(github):
    github.release = 'v1.2.3'
    rel = release.latest_release(github.url)
    assert (rel.version, rel.tag) == ('1.2.3', 'v1.2.3')
    sums = rel.asset('SHA256SUMS')
    assert sums.url == 'https://github.com/olfabref/nex5r-ascom/releases/download/v1.2.3/SHA256SUMS'
    assert sums.size == 200
    assert rel.asset('missing') is None


def test_latest_release_without_network_raises_release_error():
    with pytest.raises(release.ReleaseError):
        release.latest_release(NO_GITHUB, timeout=2)


def wait_for(predicate, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_check_repeats_and_tells_listeners_when_a_release_appears(github):
    github.release = 'v1.2.0'
    check = release.ReleaseCheck(current='1.2.0', url=github.url, interval=0.1)
    changes = []
    check.on_change.append(changes.append)
    check.start()
    try:
        wait_for(lambda: check.state()['state'] == 'up_to_date')
        assert check.update_available is False
        github.release = 'v1.3.0'                            # published while the server runs
        wait_for(lambda: check.update_available)
        assert check.latest.tag == 'v1.3.0'
        assert [c['state'] for c in changes] == ['up_to_date', 'available']
        assert changes[-1]['latest'] == '1.3.0'
    finally:
        check.stop()


def test_an_older_release_than_this_version_is_up_to_date(github):
    github.release = 'v1.1.9'
    assert release.ReleaseCheck(current='1.2.0', url=github.url).check()['state'] == 'up_to_date'


def test_https_requests_trust_the_system_certificates(monkeypatch, tmp_path):
    # python.org's Python on macOS ships no CA certificates: without the OS trust store, every GitHub
    # request failed with CERTIFICATE_VERIFY_FAILED (the Release check said "cannot check").
    import truststore
    import update
    contexts = []

    def urlopen(req, timeout=None, context=None):
        contexts.append(context)
        raise OSError('stop here')

    monkeypatch.setattr(release.urllib.request, 'urlopen', urlopen)
    with pytest.raises(release.ReleaseError):
        release.latest_release('https://example.invalid/releases/latest')
    with pytest.raises(update.UpdateError):
        update.download('https://example.invalid/setup.exe', tmp_path / 'setup.exe')
    assert len(contexts) == 2 and all(isinstance(c, truststore.SSLContext) for c in contexts)
