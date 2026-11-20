# Frozen executable on Windows, sources on Mac

On Windows (the astro mini-PC, often offline in the field), the Alpaca Server ships as a PyInstaller `onedir` executable that bundles Python and `rawpy` (a native extension), wrapped in a per-user Inno Setup installer that needs no admin rights. An Update downloads the newer Release's installer, checks its SHA-256, runs it silently and restarts the server. On Mac (the development machine) there is no installer and no Update: the server runs from the sources in a venv.

## Considered options

- **Installer that installs Python and builds a venv**: it depends on the network and PyPI at install time, so it is fragile offline.
- **Windows service**: a service cannot show a tray icon and makes replacing the files harder. The server starts at login instead.
- **`.app` / `.dmg` for Mac**: without Apple signing and notarisation ($99/year), Gatekeeper blocks it, and it brings nothing to development.
- **Windows code signing**: too expensive for personal use. The SmartScreen warning on first install is accepted.

## Consequences

The configuration lives in the user folder (`%APPDATA%` on Windows, `~/Library/Application Support` on Mac), not next to the code, so that an Update does not overwrite it.
