"""One Version for the whole repository (ADR 0001), written by release-please.

.release-please-manifest.json holds the current Version. release-please rewrites it in its release PR,
together with every file of release-please-config.json's extra-files: those files must exist, carry
the release-please marker, and agree with the manifest, so the release PR ships one Version everywhere.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SEMVER = re.compile(r'\d+\.\d+\.\d+')


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def manifest_version() -> str:
    return json.loads(read('.release-please-manifest.json'))['.']


def extra_files() -> list[str]:
    config = json.loads(read('release-please-config.json'))
    return [f if isinstance(f, str) else f['path'] for f in config['packages']['.']['extra-files']]


def test_manifest_holds_a_version():
    assert SEMVER.fullmatch(manifest_version())


def test_the_server_and_camera_app_versions_are_rewritten_by_release_please():
    assert set(extra_files()) == {'alpaca-server/version.py', 'camera-app/app/AndroidManifest.xml'}


@pytest.mark.parametrize('rel', ['alpaca-server/version.py', 'camera-app/app/AndroidManifest.xml'])
def test_every_rewritten_file_carries_the_version_of_the_manifest(rel):
    text = read(rel)
    if 'x-release-please-start-version' in text:
        block = text.split('x-release-please-start-version', 1)[1].split('x-release-please-end', 1)[0]
        lines = block.splitlines()
    else:
        lines = [line for line in text.splitlines() if 'x-release-please-version' in line]
    versions = [v for line in lines for v in SEMVER.findall(line)]
    assert versions == [manifest_version()], (rel, versions)


def test_android_manifest_version_name_is_the_version():
    assert f'android:versionName="{manifest_version()}"' in read('camera-app/app/AndroidManifest.xml')


def test_release_workflow_uses_the_release_please_token():
    workflow = yaml.safe_load(read('.github/workflows/release.yml'))
    steps = [s for job in workflow['jobs'].values() for s in job.get('steps', [])]
    rp = [s for s in steps if s.get('uses', '').startswith('googleapis/release-please-action@')]
    assert len(rp) == 1
    assert rp[0]['with']['token'] == '${{ secrets.RELEASE_PLEASE_TOKEN }}'
    # The PAT wizard stores the secret under the name the workflow reads
    assert 'set_secret RELEASE_PLEASE_TOKEN' in read('.github/scripts/release-please-token.sh')
