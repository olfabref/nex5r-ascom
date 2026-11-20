# Contributing

GitHub flow: every change goes through a pull request into `main`, merged with **squash merge only**. The PR title becomes the commit message on `main`, so it must follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(alpaca-server): Focuser device`, `fix: …`, `docs: …`.

## CI

`.github/workflows/ci.yml` runs on every PR. Each job is a required check of `main`:

- `pytest (ubuntu-latest)`, `pytest (windows-latest)`, `pytest (macos-latest)`: the Alpaca Server tests and the workflow policy tests (`.github/tests/`), on Python 3.12.
- `camera-app APK`: builds `camera-app/build/nex5r.apk`, with the Android SDK, the build-tools and `camera-app/deps.sh` fetched by the workflow.
- `PR title`: checks the title with `.github/scripts/check_pr_title.py`.

Locally:

```sh
pip install -r alpaca-server/requirements-dev.txt -r .github/tests/requirements.txt
(cd alpaca-server && python -m pytest)
python -m pytest .github/tests
PR_TITLE="feat: something" python .github/scripts/check_pr_title.py
```

CI logs are public and PRs may come from forks. Workflows run on `pull_request` (never `pull_request_target`), `GITHUB_TOKEN` is `contents: read` by default, and event values reach the shell through `env:` only. `.github/tests/test_workflows.py` enforces this. Never print an IP address, a personal path or a secret in a workflow.

## Protection of `main` (repository admin, once)

```sh
.github/scripts/protect-main.sh
```

The wizard sets squash merge only, then protects `main`: PR required, required checks up to date, linear history, no force push or deletion, enforced for admins (no bypass). Run it after CI has run at least once on a PR. If a CI job is renamed, update `CHECKS` in the script and re-run it.
