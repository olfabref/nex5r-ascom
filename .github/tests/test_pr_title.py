"""The PR title check: with squash merge, the PR title becomes the commit message on main,
so it must follow Conventional Commits."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'check_pr_title.py'


def check(title: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], env={**os.environ, 'PR_TITLE': title},
                          capture_output=True, text=True)


@pytest.mark.parametrize('title', [
    'feat: Focuser device',
    'fix(alpaca-server): reconnect after a Wi-Fi drop',
    'feat!: drop the old config format',
    'refactor(camera-app)!: new HTTP routes',
    'docs: N.I.N.A. settings',
    'ci: PR workflow',
    'chore(deps): bump numpy',
    'chore(main): release 0.1.0',  # the release-please PR
])
def test_conventional_title_passes(title):
    assert check(title).returncode == 0


@pytest.mark.parametrize('title', [
    'update stuff',
    'feat:missing space',
    'feat: ',
    'Feat: capitalised type',
    'feature: unknown type',
    'feat(): empty scope',
    '',
])
def test_other_titles_fail_with_a_hint(title):
    result = check(title)
    assert result.returncode == 1
    assert 'Conventional Commits' in result.stderr
