#!/bin/sh
# Downloads the build dependencies into .deps/ and checks their checksums.
set -eu
cd "$(dirname "$0")"
mkdir -p .deps

fetch() { # url dest algo checksum
  if [ ! -f "$2" ]; then
    echo "Downloading $(basename "$2")"
    curl -fsSL --retry 3 -o "$2.part" "$1"
    mv "$2.part" "$2"
  fi
  echo "$4  $2" | shasum -a "$3" -c - >/dev/null || { echo "Bad checksum: $2" >&2; rm -f "$2"; exit 1; }
}

# Android 2.3.3 platform (API 10), the NEX-5R's Android version. Checksum from Google's repository2-1.xml.
fetch https://dl.google.com/android/repository/android-2.3.3_r02.zip \
  .deps/android-2.3.3_r02.zip 1 887e37783ec32f541ea33c2c649dda648e8e6fb3
if [ ! -f .deps/android.jar ]; then
  unzip -q -j -o .deps/android-2.3.3_r02.zip '*/android.jar' -d .deps
fi

# OpenMemories: Framework (MIT, ma1co) from jitpack. Checksums pinned on 2026-11-02.
J=https://jitpack.io/com/github/ma1co/OpenMemories-Framework
fetch $J/framework/master-SNAPSHOT/framework-master-SNAPSHOT.jar \
  .deps/openmemories-framework.jar 256 0fa23691853ea94e5187cb9f7be5d357c67e4041cde967c03c74958438b3a2db
fetch $J/stubs/master-SNAPSHOT/stubs-master-SNAPSHOT.jar \
  .deps/openmemories-stubs.jar 256 6ffca47cf4218289728e28535664a78d4ea4f79ff6b48b4d96e3084ba9b33fb5

echo "Dependencies OK"
