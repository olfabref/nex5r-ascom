# Builds the Windows installer of the Alpaca Server (ADR 0002), on Windows with Python 3.12:
#
#     pwsh alpaca-server/installer/build.ps1
#
# 1. PyInstaller freezes the server (installer/nex5r-ascom.spec) into alpaca-server/dist/nex5r-ascom;
# 2. Inno Setup 6 wraps it (installer/nex5r-ascom.iss) into alpaca-server/dist/nex5r-ascom-setup.exe,
#    with the Version of version.py.
# Inno Setup is installed with Chocolatey when ISCC.exe is missing (GitHub Windows runners have choco).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Invoke-Checked {
    & $args[0] $args[1..($args.Length - 1)]
    if ($LASTEXITCODE) { throw "$($args[0]) exited with $LASTEXITCODE" }
}

Invoke-Checked python -m pip install -r requirements.txt -r installer/requirements-build.txt
Invoke-Checked python -m PyInstaller --noconfirm --clean installer/nex5r-ascom.spec

$version = (python -c 'from version import __version__; print(__version__)').Trim()
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $iscc)) {
    Invoke-Checked choco install innosetup --no-progress -y
}
Invoke-Checked $iscc "/DAppVersion=$version" installer/nex5r-ascom.iss
Write-Output "Built dist/nex5r-ascom-setup.exe, Version $version"
