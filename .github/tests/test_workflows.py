"""Security policy for every GitHub Actions workflow of the repository.

CI logs are public and PRs can come from forks, so:
- no workflow runs on pull_request_target (which gives fork code access to secrets);
- GITHUB_TOKEN gets `contents: read` by default, and a job may only widen it explicitly;
- no `run:` step interpolates `${{ github.event... }}` (a crafted PR title would become shell code).
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / 'workflows').glob('*.y*ml'))


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    data['on'] = data.pop(True, data.get('on'))  # YAML 1.1 reads the `on` key as True
    return data


def test_there_are_workflows():
    assert WORKFLOWS


@pytest.mark.parametrize('path', WORKFLOWS, ids=lambda p: p.name)
def test_no_pull_request_target(path):
    triggers = load(path)['on']
    names = [triggers] if isinstance(triggers, str) else list(triggers)
    assert 'pull_request_target' not in names


@pytest.mark.parametrize('path', WORKFLOWS, ids=lambda p: p.name)
def test_token_is_read_only_by_default(path):
    assert load(path).get('permissions') == {'contents': 'read'}


@pytest.mark.parametrize('path', WORKFLOWS, ids=lambda p: p.name)
def test_run_steps_do_not_interpolate_event_values(path):
    for job in load(path)['jobs'].values():
        for step in job.get('steps', []):
            assert not re.search(r'\$\{\{\s*github\.(event|head_ref)', step.get('run', '')), step
