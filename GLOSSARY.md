# nex5r-ascom

Driving a Sony NEX-5R and its focus-by-wire lens from N.I.N.A., through ASCOM Alpaca.

## Components

**Camera**:
The physical Sony NEX-5R body, with its lens.
_Avoid_: body, device (alone)

**camera-app**:
The Android app running on the Camera, which exposes its functions over HTTP on Wi-Fi.
_Avoid_: camera app, NEX5R Dev, the app

**Alpaca Server**:
The program that turns N.I.N.A.'s ASCOM Alpaca calls into calls to camera-app, and that exposes the two Devices.
_Avoid_: driver, server (alone), alpyca

**Camera device** / **Focuser device**:
The two ASCOM Alpaca devices exposed by the Alpaca Server: the Camera as an imaging sensor, and its lens as a focuser.
_Avoid_: camera (for the device), focus

**Dashboard**:
The Alpaca Server's status page, which shows the state of the components and offers the Update.
_Avoid_: UI, GUI, IHM, setup page

## States

**Reachable**:
camera-app answers the Alpaca Server over the network.
_Avoid_: connected (for the network), online

**Connected**:
A Device is connected in the Alpaca sense: a client such as N.I.N.A. is driving it.
_Avoid_: reachable, active

**Arming**:
The Camera autofocus that sets the reference point of the focus offsets; without it, any offset freezes the Camera. Position 16 is the Arming point.
_Avoid_: calibration, initialisation

## Delivery

**Version**:
The `vX.Y.Z` number shared by the Alpaca Server and camera-app.
_Avoid_: build, revision

**Release**:
What is delivered for a Version: the Alpaca Server's Windows installer and the camera-app APK.
_Avoid_: deliverable, package

**Update**:
Replacing the installed Alpaca Server with the one from a newer Release, started from the Dashboard. camera-app is not part of it.
_Avoid_: upgrade, auto-update
