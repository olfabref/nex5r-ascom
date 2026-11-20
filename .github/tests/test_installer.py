"""The Windows installer of the Alpaca Server (ADR 0002): a PyInstaller `onedir` bundle wrapped in a
per-user Inno Setup installer, built by the release workflow and attached to the Release with SHA256SUMS.

The installer itself only runs on Windows (installer/check_install.py, in CI on a Windows runner);
these tests check, on every OS, what the build and the Release depend on.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SERVER = ROOT / 'alpaca-server'
INSTALLER = SERVER / 'installer'
ASSET = 'nex5r-ascom-setup.exe'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def workflow(name: str) -> dict:
    return yaml.safe_load(read(ROOT / '.github' / 'workflows' / name))


def run_scripts(job: dict) -> str:
    return '\n'.join(step.get('run', '') for step in job.get('steps', []))


def iss_entries(section: str) -> list[str]:
    """The lines of one [Section] of the Inno Setup script."""
    text = read(INSTALLER / 'nex5r-ascom.iss')
    for name, value in re.findall(r'^\s*#define\s+(\w+)\s+"([^"]*)"', text, re.M):
        text = text.replace('{#' + name + '}', value)
    body = re.search(rf'^\[{section}\]\s*$(.*?)(?=^\[|\Z)', text, re.M | re.S)
    return [line.strip() for line in body.group(1).splitlines()
            if line.strip() and not line.strip().startswith(';')] if body else []


def iss_setup(key: str) -> str:
    values = [line.split('=', 1)[1].strip() for line in iss_entries('Setup')
              if line.split('=', 1)[0].strip().lower() == key.lower()]
    assert len(values) == 1, key
    return values[0]


def files_read_next_to_the_code() -> set[str]:
    """Data files the server opens relative to its own module (Path(__file__)...'name.ext')."""
    names = set()
    for source in SERVER.glob('*.py'):
        for line in read(source).splitlines():
            if 'Path(__file__)' in line:
                names.update(re.findall(r"""['"]([\w-]+\.(?!py\b)\w+)['"]""", line))
    return names


def test_pyinstaller_bundles_every_file_the_server_reads_next_to_its_code():
    names = files_read_next_to_the_code()
    assert {'config-template.toml', 'dashboard.html'} <= names
    spec = read(INSTALLER / 'nex5r-ascom.spec')
    for name in names:
        # bundled at the root of the bundle, next to the frozen modules (Path(__file__).parent)
        assert re.search(rf"""\([^()'"]*['"][^'"]*{re.escape(name)}['"]\s*,\s*['"]\.['"]\s*\)""", spec), name


def test_pyinstaller_bundles_the_windows_tray_icon_backend():
    # tray.py imports pystray lazily, and pystray picks its backend module at run time
    spec = read(INSTALLER / 'nex5r-ascom.spec')
    hidden = re.search(r'hiddenimports\s*=\s*\[([^\]]*)\]', spec)
    assert hidden and "'pystray._win32'" in hidden.group(1)
    assert 'pystray' in read(SERVER / 'requirements.txt')


def test_installer_is_per_user_without_admin_rights():
    assert iss_setup('PrivilegesRequired') == 'lowest'
    assert iss_setup('DefaultDirName').startswith('{localappdata}')


def test_installer_file_is_the_release_asset():
    assert iss_setup('OutputBaseFilename') + '.exe' == ASSET


def test_installer_starts_the_server_at_login_with_a_working_folder():
    startup = [e for e in iss_entries('Icons') if '{userstartup}' in e]
    assert len(startup) == 1
    assert 'nex5r-ascom.exe' in startup[0] and 'WorkingDir:' in startup[0]


def test_installer_never_touches_the_configuration_in_the_user_folder():
    # config.toml lives in %APPDATA%\nex5r-ascom (config.user_config_path): reinstall and uninstall keep it
    for section in ('Files', 'Dirs', 'InstallDelete', 'UninstallDelete'):
        for entry in iss_entries(section):
            assert '{userappdata}' not in entry and '{app}' in entry, (section, entry)


def installer_jobs(workflow_name: str) -> dict:
    """Jobs of a workflow that build the installer on Windows and run the end-to-end check on it."""
    return {name: job for name, job in workflow(workflow_name)['jobs'].items()
            if str(job.get('runs-on', '')).startswith('windows')
            and 'installer/build.ps1' in run_scripts(job)
            and 'installer/check_install.py' in run_scripts(job)}


def test_pull_requests_build_and_check_the_installer_on_windows():
    assert installer_jobs('ci.yml')


def test_release_attaches_the_checked_installer_with_its_checksum():
    jobs = workflow('release.yml')['jobs']
    [windows] = installer_jobs('release.yml')
    assets = jobs['assets']
    assert windows in assets['needs']
    script = run_scripts(assets)
    sums = [line for line in script.splitlines() if 'sha256sum' in line]
    upload = [line for line in script.splitlines() if 'gh release upload' in line]
    assert sums and ASSET in sums[0]
    assert upload and ASSET in upload[0] and 'SHA256SUMS' in upload[0]
