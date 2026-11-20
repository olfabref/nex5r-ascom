# PyInstaller spec of the Alpaca Server for Windows (ADR 0002): `onedir`, Python and rawpy included.
#
#     cd alpaca-server && python -m PyInstaller --noconfirm installer/nex5r-ascom.spec
#
# Output: alpaca-server/dist/nex5r-ascom/nex5r-ascom.exe, wrapped by installer/nex5r-ascom.iss.
# Data files the server reads next to its own modules (Path(__file__).parent) go to the root of the
# bundle ('.'), where the frozen modules live: .github/tests/test_installer.py checks that none is missing.
from PyInstaller.utils.hooks import collect_dynamic_libs

SERVER = SPECPATH + '/..'

a = Analysis(
    [SERVER + '/app.py'],
    pathex=[SERVER],
    datas=[
        (SERVER + '/config-template.toml', '.'),
        (SERVER + '/dashboard.html', '.'),
    ],
    binaries=collect_dynamic_libs('rawpy'),
    runtime_hooks=[SPECPATH + '/rthook_streams.py'],
    excludes=['tkinter'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='nex5r-ascom',
    console=False,      # started at login: no console window. Logs: alpyca.log in the working folder.
)
coll = COLLECT(exe, a.binaries, a.datas, name='nex5r-ascom')
