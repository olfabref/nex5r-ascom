"""The Alpaca Server knows its Version (ADR 0001): the one release-please records in
.release-please-manifest.json at the repository root."""
import json
import time

import pytest

from conftest import SERVER_DIR

MANIFEST = SERVER_DIR.parent / '.release-please-manifest.json'


@pytest.fixture
def version() -> str:
    return json.loads(MANIFEST.read_text(encoding='utf-8'))['.']


@pytest.mark.parametrize('device', ['camera', 'focuser'])
def test_both_devices_report_the_version_as_driver_version(alpaca, version, device):
    assert alpaca.get(device, 'driverversion') == version


def test_server_description_reports_the_version(alpaca, version):
    assert alpaca.call('GET', '/management/v1/description')['Value']['Version'] == version


def test_startup_log_names_the_version(alpaca, version, tmp_path):
    log = tmp_path / 'alpyca.log'
    deadline = time.monotonic() + 5
    while f'Version {version}' not in (log.read_text(encoding='utf-8') if log.exists() else ''):
        assert time.monotonic() < deadline, log.read_text(encoding='utf-8') if log.exists() else 'no log'
        time.sleep(0.05)
