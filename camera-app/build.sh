#!/bin/sh
# Builds build/nex5r.apk for the NEX-5R (Android 2.3.7, API 10). No Gradle: aapt + javac + d8 + apksigner.
set -eu
cd "$(dirname "$0")"

SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BT="$SDK/build-tools/${BUILD_TOOLS_VERSION:-$(ls "$SDK/build-tools" | sort -V | tail -1)}"  # default: the newest
DEPS=.deps
ANDROID_JAR=$DEPS/android.jar
FRAMEWORK_JAR=$DEPS/openmemories-framework.jar
STUBS_JAR=$DEPS/openmemories-stubs.jar   # compile-only: the real classes are on the camera
KEYSTORE="${KEYSTORE:-$HOME/.android/debug.keystore}"

[ -f "$ANDROID_JAR" ] && [ -f "$FRAMEWORK_JAR" ] && [ -f "$STUBS_JAR" ] || ./deps.sh

rm -rf build && mkdir -p build/gen build/classes build/dex

echo "1/5 Resources"
"$BT/aapt" package -f -m -J build/gen -M app/AndroidManifest.xml -S app/res -I "$ANDROID_JAR"

echo "2/5 Java"
find app/src build/gen -name '*.java' > build/sources.txt
javac -nowarn -Xlint:-options -encoding UTF-8 -source 8 -target 8 \
  -bootclasspath "$ANDROID_JAR" -cp "$FRAMEWORK_JAR:$STUBS_JAR" \
  -d build/classes @build/sources.txt

echo "3/5 Dex"
find build/classes -name '*.class' > build/classes.txt
"$BT/d8" --release --min-api 10 --lib "$ANDROID_JAR" --classpath "$STUBS_JAR" \
  --output build/dex @build/classes.txt "$FRAMEWORK_JAR"

echo "4/5 Package"
# The Version is the manifest's versionName (written by release-please); versionCode is derived
# from it (X.Y.Z -> X*10000 + Y*100 + Z, at least 1), so a newer Version always has a higher code.
VERSION_NAME=$(sed -n 's/.*android:versionName="\([0-9]*\.[0-9]*\.[0-9]*\)".*/\1/p' app/AndroidManifest.xml)
[ -n "$VERSION_NAME" ] || { echo "No X.Y.Z android:versionName in app/AndroidManifest.xml" >&2; exit 1; }
VERSION_CODE=$(echo "$VERSION_NAME" | awk -F. '{ c = $1 * 10000 + $2 * 100 + $3; print (c < 1 ? 1 : c) }')
"$BT/aapt" package -f -M app/AndroidManifest.xml -S app/res -I "$ANDROID_JAR" \
  --version-code "$VERSION_CODE" -F build/unsigned.apk
(cd build/dex && zip -q ../unsigned.apk classes.dex)
"$BT/zipalign" -f 4 build/unsigned.apk build/aligned.apk

echo "5/5 Sign"
# v1 (JAR) signature only: Android 2.3 ignores v2+. The camera accepts debug certificates.
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:android --min-sdk-version 10 \
  --v2-signing-enabled false --v3-signing-enabled false --out build/nex5r.apk build/aligned.apk

echo "Built build/nex5r.apk (Version $VERSION_NAME, versionCode $VERSION_CODE)"
