package com.github.olfabref.nex5r;

import android.hardware.Camera;
import android.os.Handler;

import com.sony.scalar.hardware.CameraEx;

import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Lens focus through CameraEx.shiftFocusPosition(offset), shared by the focus page (keys) and HTTP
 * (/focus, /focusarm) so both see the same state.
 *
 * What we know on the NEX-5R (fw 1.03, see brief.md):
 * - the argument is an ABSOLUTE offset from a reference point, within [-16, 16];
 * - the call blocks forever (and freezes the camera) unless an autofocus was started since the
 *   camera was opened: {@link #moveTo} refuses to run before {@link #arm};
 * - the lens only moves if that autofocus ran in focus-mode auto (or dmf) and the mode is still
 *   auto / dmf; an autofocus in manual arms without moving the lens, but offsets then do nothing;
 * - the call must not run on the UI thread (it never returns there); each call takes 230-300 ms.
 *
 * Camera parameters and autoFocus run on the UI thread (handler); shiftFocusPosition runs on the
 * caller's thread, which must not be the UI thread.
 */
final class FocusControl {
    static final int MIN_OFFSET = -16;   // min-focus-shift
    static final int MAX_OFFSET = 16;    // max-focus-shift
    private static final long AF_WAIT_MS = 3000;     // longest wait for onAutoFocusDone
    private static final long SHIFT_TIMEOUT_MS = 10000;

    private final Handler handler;
    private volatile CameraEx camera;
    private volatile boolean armed = false;
    private volatile int offset = 0;               // last offset the camera accepted
    private volatile long pendingSince = 0;        // start of the running shift call, 0 if none
    private volatile CountDownLatch afDone;        // counted down by BulbTest's AutoFocusDoneListener
    private volatile String lastResult = "-";
    private int calls = 0;
    private int failures = 0;

    FocusControl(Handler handler) { this.handler = handler; }

    void attach(CameraEx cam) {
        camera = cam;
        armed = false;
        offset = 0;
    }

    void detach() {
        camera = null;
        armed = false;
    }

    boolean isArmed() { return armed; }

    boolean isMoving() { return pendingSince != 0; }

    int offset() { return offset; }

    String lastResult() { return lastResult; }

    int calls() { return calls; }

    int failures() { return failures; }

    /** Called by BulbTest's AutoFocusDoneListener (UI thread). */
    void onAutoFocusDone(int status) {
        CountDownLatch l = afDone;
        if (l != null) l.countDown();
    }

    /**
     * Autofocus in the given focus mode ("auto", "dmf", "manual", or "" to keep the current one),
     * which arms the shifts and makes the current lens position offset 0. Blocks until the camera
     * reports the end of the autofocus (at most AF_WAIT_MS). Not on the UI thread.
     */
    String arm(final String mode) {
        if (camera == null) return result("no camera");
        if (isMoving()) return result("busy: shift running");
        afDone = new CountDownLatch(1);
        String started = onUi(new Callable<String>() {
            public String call() {
                CameraEx cam = camera;
                if (cam == null) return "no camera";
                try {
                    if (mode.length() > 0) setFocusModeNow(cam, mode);
                    cam.getNormalCamera().autoFocus(null);
                    armed = true;
                    offset = 0;
                    return null;
                } catch (Throwable t) {
                    return "autofocus threw " + t;
                }
            }
        });
        if (started != null) return result(started);
        boolean done = false;
        try {
            done = afDone.await(AF_WAIT_MS, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            // report what we have
        }
        afDone = null;
        return result("armed: autofocus in " + focusMode() + (done ? ", done" : ", no AF-done event after "
                + AF_WAIT_MS + " ms") + "; offset 0");
    }

    /**
     * Sends one offset (clamped to [MIN_OFFSET, MAX_OFFSET]) and waits for the camera. Not on the UI
     * thread. Refused before arm() (the call would freeze the camera) and while a shift runs.
     */
    String moveTo(int target) {
        final CameraEx cam = camera;
        if (cam == null) return result("no camera");
        if (!armed) return result("not armed: call /focusarm first");
        int t = Math.max(MIN_OFFSET, Math.min(MAX_OFFSET, target));
        synchronized (this) {
            if (pendingSince != 0) return result("busy: shift running");
            pendingSince = System.currentTimeMillis();
            calls++;
        }
        long start = pendingSince;
        Logger.info("shift(" + t + ") calling | offset " + offset + " | focus-mode " + focusMode());
        final boolean[] ok = {false};
        final Throwable[] err = {null};
        final CountDownLatch done = new CountDownLatch(1);
        final int steps = t;
        // A helper thread, so that a hung call does not block the caller (an HTTP client) forever.
        new Thread(new Runnable() {
            public void run() {
                try {
                    ok[0] = cam.shiftFocusPosition(steps);
                } catch (Throwable e) {
                    err[0] = e;
                }
                done.countDown();
            }
        }, "focus-shift").start();
        boolean returned = false;
        try {
            returned = done.await(SHIFT_TIMEOUT_MS, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            // reported below
        }
        long ms = System.currentTimeMillis() - start;
        if (!returned) {
            // Leave pendingSince set: the call is still running and the camera will refuse others.
            failures++;
            return result("HANG: shift(" + t + ") still running after " + ms + " ms");
        }
        pendingSince = 0;
        if (err[0] != null) {
            failures++;
            return result("shift(" + t + ") threw " + err[0]);
        }
        if (!ok[0]) {
            failures++;
            return result("shift(" + t + ") -> false in " + ms + " ms");
        }
        offset = t;
        return result("shift(" + t + ") -> true in " + ms + " ms");
    }

    /** Sets the focus mode (auto, dmf, manual). Not on the UI thread. */
    String setFocusMode(final String mode) {
        return result(onUi(new Callable<String>() {
            public String call() {
                CameraEx cam = camera;
                if (cam == null) return "no camera";
                try {
                    setFocusModeNow(cam, mode);
                    return "focus-mode -> " + focusMode();
                } catch (Throwable t) {
                    return "focus-mode " + mode + " threw " + t;
                }
            }
        }));
    }

    private static void setFocusModeNow(CameraEx cam, String mode) {
        Camera.Parameters params = cam.getNormalCamera().getParameters();
        params.setFocusMode(mode);
        cam.getNormalCamera().setParameters(params);
    }

    String focusMode() {
        try {
            return camera.getNormalCamera().getParameters().getFocusMode();
        } catch (Throwable t) {
            return "?";
        }
    }

    /** One "key=value" line per field, for HTTP /status and /focus. */
    String state() {
        return "focus_armed=" + armed + "\nfocus_offset=" + offset + "\nfocus_moving=" + isMoving()
                + "\nfocus_min=" + MIN_OFFSET + "\nfocus_max=" + MAX_OFFSET
                + "\nfocus_mode=" + (camera == null ? "-" : focusMode()) + "\nfocus_last=" + lastResult + "\n";
    }

    private String result(String s) {
        lastResult = s;
        Logger.info("focus: " + s);
        return s;
    }

    /** Runs call on the UI thread and waits up to 5 s; null result = success for arm(). */
    private String onUi(final Callable<String> call) {
        final String[] out = {"timeout waiting for the UI thread"};
        final CountDownLatch done = new CountDownLatch(1);
        handler.post(new Runnable() {
            public void run() {
                try {
                    out[0] = call.call();
                } catch (Throwable t) {
                    out[0] = "threw " + t;
                }
                done.countDown();
            }
        });
        try {
            done.await(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            // return what we have
        }
        return out[0];
    }
}
