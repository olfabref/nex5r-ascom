# camera-app

The Android app that runs on the NEX-5R (Android 2.3.7, API 10), built against OpenMemories: Framework.

No Gradle: the old Android Gradle plugin and jcenter no longer work. `build.sh` calls the SDK tools directly.

## Prerequisites (macOS)

- JDK 11+ (`javac`) and the Android SDK build-tools (`aapt`, `d8`, `zipalign`, `apksigner`) in `~/Library/Android/sdk` or `$ANDROID_HOME`. The newest build-tools are used unless `BUILD_TOOLS_VERSION` is set (CI pins it).
- A debug keystore at `~/.android/debug.keystore` (password `android`), or set `KEYSTORE`.
- Sony-PMCA-RE in `~/dev/Sony-PMCA-RE` with its `.venv` (or set `PMCA_HOME`), for installing.

## Usage

```sh
./deps.sh      # once: downloads the API 10 android.jar and the OpenMemories jars into .deps/, checksums verified
./build.sh     # -> build/nex5r.apk
./install.sh   # camera on USB, in MTP mode
```

On the camera: Menu → Application → **NEX5R Dev**. The trash button exits.

## Debugging

The camera restarts its Android side whenever an app starts or exits, which wipes logcat and drops Wi-Fi/adb. The app logs to `NEX5R/LOG.TXT` on the SD card instead. Read it over adb while NEX5R Dev runs (the app turns Wi-Fi on and starts adbd itself; adb stops when the app exits):

```sh
adb connect <camera-ip>:5555
adb shell cat /sdcard/NEX5R/LOG.TXT
```
