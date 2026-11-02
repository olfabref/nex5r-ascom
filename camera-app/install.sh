#!/bin/sh
# Installs an APK (default: build/nex5r.apk) on the NEX-5R over USB with Sony-PMCA-RE.
# Camera must be in "USB Connection: MTP". macOS's ptpcamerad grabs the camera every time it
# reconnects (the install switches USB modes), so it is killed in a loop for the whole install.
set -eu
cd "$(dirname "$0")"
APK="$(cd "$(dirname "${1:-build/nex5r.apk}")" && pwd)/$(basename "${1:-build/nex5r.apk}")"
PMCA="${PMCA_HOME:-$HOME/dev/Sony-PMCA-RE}"

( while true; do pkill -9 -x ptpcamerad 2>/dev/null || true; sleep 0.2; done ) &
KILLER=$!
trap 'kill $KILLER 2>/dev/null' EXIT INT TERM

"$PMCA/.venv/bin/python" -W ignore "$PMCA/pmca-console.py" install -f "$APK"
