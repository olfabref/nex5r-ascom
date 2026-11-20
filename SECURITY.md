# Security

## Threat model

This project is meant for a **trusted local network**: a home network, or the private Wi-Fi of an astro setup in the field. None of its parts has any authentication:

- **Alpaca Server**: like any ASCOM Alpaca server, it listens on all interfaces (HTTP port 11111, discovery on UDP 32227). Anyone on the network can drive the Camera device and the Focuser device.
- **Dashboard**: served by the Alpaca Server. Anyone on the network can view the state, change the Camera address and `sensor_type`, re-arm the Focuser and start an Update.
- **camera-app**: its HTTP server on the Camera (port 8080) exposes the camera controls, the files on the SD card and debug routes (logs, logcat, key events…).

Do not expose these ports to the Internet, and do not run them on an untrusted network (public Wi-Fi, shared networks).

## Updates

The Update downloads the installer of the newest GitHub Release over HTTPS and checks it against the `SHA256SUMS` file of the same Release before running it. The installer is not code-signed, so Windows SmartScreen warns on the first manual install.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on this repository. Do not open a public issue.
