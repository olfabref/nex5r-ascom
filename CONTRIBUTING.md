# Contributing

GitHub flow: every change goes through a pull request into `main`, merged with **squash merge only**. The PR title becomes the commit message on `main`, so it must follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(alpaca-server): Focuser device`, `fix: …`, `docs: …`.

## CI

`.github/workflows/ci.yml` runs on every PR. Each job is a required check of `main`:

- `pytest (ubuntu-latest)`, `pytest (windows-latest)`, `pytest (macos-latest)`: the Alpaca Server tests and the workflow policy tests (`.github/tests/`), on Python 3.12.
- `camera-app APK`: builds `camera-app/build/nex5r.apk`, with the Android SDK, the build-tools and `camera-app/deps.sh` fetched by the workflow.
- `Windows installer`: builds `nex5r-ascom-setup.exe` and checks it end to end (`alpaca-server/installer/check_install.py`, see `alpaca-server/README.md`).
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

## Releases

`.github/workflows/release.yml` runs [release-please](https://github.com/googleapis/release-please) on every push to `main`. It keeps a release PR open (`chore(main): release X.Y.Z`) with the next Version computed from the Conventional Commits (`feat:` bumps the minor before 1.0, `fix:` the patch), `CHANGELOG.md`, and that Version written into `.release-please-manifest.json`, `alpaca-server/version.py` and `camera-app/app/AndroidManifest.xml` (`release-please-config.json`). Never edit these Versions by hand: `.github/tests/test_release.py` checks that they agree.

Merging the release PR creates the `vX.Y.Z` tag and the GitHub Release; the `Windows installer` job builds and checks the installer at that tag, and the `Release assets` job builds the APK and attaches `nex5r.apk`, `nex5r-ascom-setup.exe` and `SHA256SUMS`.

release-please authenticates with a fine-grained PAT in the `RELEASE_PLEASE_TOKEN` secret, so that CI (the required checks) runs on its PR: a PR opened with `GITHUB_TOKEN` triggers no workflow. The token has access to this repository only, with `Contents` and `Pull requests` read and write, and expires after one year. To create or renew it (repository admin):

```sh
.github/scripts/release-please-token.sh
```
