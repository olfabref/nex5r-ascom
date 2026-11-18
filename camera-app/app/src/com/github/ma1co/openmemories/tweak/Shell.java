package com.github.ma1co.openmemories.tweak;

import android.os.Process;

/**
 * Same package and name as OpenMemories: Tweak's Shell, so that Tweak's installed libtweak.so binds to it
 * (its JNI functions are looked up by name, there is no JNI_OnLoad). Copied from
 * https://github.com/ma1co/OpenMemories-Tweak (app/src/main/java/.../Shell.java); the library is loaded
 * from Tweak's own install by {@link #load(String)} instead of being bundled.
 */
public class Shell {
    private static native void nativeExec(String command) throws NativeException;

    /** Loads Tweak's libtweak.so from its native library directory. */
    public static void load(String tweakLibDir) {
        System.load(tweakLibDir + "/libtweak.so");
    }

    public static void exec(String command) throws NativeException {
        nativeExec(command);
    }

    /** Runs a command in the Android chroot with this process's environment (Tweak's code, unchanged). */
    public static void execAndroid(String command) throws NativeException {
        int pid = Process.myPid();
        exec("ps e --no-heading " + pid + " | (" +
                 "read _ _ _ _ _ e;" +
                 "export $e;" +
                 "echo $ANDROID_PROPERTY_WORKSPACE | (" +
                     "IFS=, read f _;" +
                     "eval \"exec $f< /proc/" + pid + "/fd/$f\";" +
                     "/bin/busybox chroot /android " + command +
                 ")" +
             ")");
    }
}
