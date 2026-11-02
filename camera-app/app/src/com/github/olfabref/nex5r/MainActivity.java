package com.github.olfabref.nex5r;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.github.ma1co.openmemories.framework.DeviceInfo;
import com.github.ma1co.openmemories.framework.DisplayManager;
import com.sony.scalar.hardware.CameraEx;
import com.sony.scalar.sysutil.ScalarInput;

/**
 * Focus test: live view plus calls to CameraEx.shiftFocusPosition(offset).
 *
 * What we know on the NEX-5R (fw 1.03):
 * - the argument is an ABSOLUTE offset from a reference point, within [-16, 16];
 * - the call blocks forever (and freezes the camera) unless an autofocus was started since the
 *   app opened, even in manual focus mode where AF does not move the lens;
 * - the call must not run on the UI thread.
 *
 * Left / right: move the target offset by -/+ step. Up / down: change step size.
 * Enter: cycle focus mode (auto, dmf, manual). Half-press: autofocus. Full press: take a picture.
 * Trash: exit. Every action is logged to NEX5R/LOG.TXT on the SD card.
 */
public class MainActivity extends Activity implements SurfaceHolder.Callback {
    private static final int MIN_OFFSET = -16;   // min-focus-shift
    private static final int MAX_OFFSET = 16;    // max-focus-shift
    private static final int[] STEP_SIZES = {1, 2, 4, 8, 16};
    private static final long ARM_DELAY_MS = 1000;
    private static final long HANG_MS = 5000;

    private SurfaceHolder surfaceHolder;
    private TextView overlay;
    private DisplayManager displayManager;
    private CameraEx camera;

    private int stepIndex = 0;
    private int offset = 0;        // last offset the camera accepted
    private boolean armed = false; // an autofocus was started since the camera was opened
    private int calls = 0;
    private int failures = 0;
    private String lastResult = "-";
    private volatile long pendingSince = 0;   // start time of the running shift call, 0 if none
    private boolean hangLogged = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Logger.installCrashHandler();

        SurfaceView surfaceView = new SurfaceView(this);
        surfaceHolder = surfaceView.getHolder();
        surfaceHolder.setType(SurfaceHolder.SURFACE_TYPE_PUSH_BUFFERS);

        overlay = new TextView(this);
        overlay.setTextSize(16);
        overlay.setTextColor(Color.WHITE);
        overlay.setShadowLayer(2, 1, 1, Color.BLACK);
        overlay.setGravity(Gravity.TOP | Gravity.LEFT);
        overlay.setPadding(10, 10, 10, 10);

        FrameLayout layout = new FrameLayout(this);
        layout.addView(surfaceView);
        layout.addView(overlay);
        setContentView(layout);
    }

    @Override
    protected void onResume() {
        super.onResume();
        notifyAppInfo();

        displayManager = DisplayManager.create(this);
        // Live view and UI overlay only show correctly together in low color depth (as in PMCADemo).
        displayManager.setColorDepth(DisplayManager.ColorDepth.LOW);

        DeviceInfo info = DeviceInfo.getInstance();
        Logger.info("=== Focus test start: " + info.getModel() + " fw " + info.getFirmwareVersion()
                + " api " + info.getApiVersion());

        try {
            camera = CameraEx.open(0, null);
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            Logger.info("Camera parameters: " + params.flatten());
        } catch (Throwable t) {
            Logger.error("Opening the camera failed", t);
            lastResult = "camera open FAILED: " + t;
        }
        surfaceHolder.addCallback(this);
        refresh();
    }

    @Override
    protected void onPause() {
        super.onPause();
        surfaceHolder.removeCallback(this);
        if (camera != null) {
            camera.release();
            camera = null;
        }
        if (displayManager != null) {
            displayManager.setColorDepth(DisplayManager.ColorDepth.HIGH);
            displayManager.release();
            displayManager = null;
        }
        armed = false;
        Logger.info("=== Focus test end: offset " + offset + ", " + calls + " calls, " + failures + " failed");
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        if (camera == null) return;
        try {
            camera.getNormalCamera().setPreviewDisplay(holder);
            camera.getNormalCamera().startPreview();
        } catch (Throwable t) {
            Logger.error("Starting the preview failed", t);
        }
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {}

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        int scan = event.getScanCode();
        if (event.getRepeatCount() > 0) {
            // Ignore auto-repeat so one press = one call.
            return isHandled(scan) || super.onKeyDown(keyCode, event);
        }
        if (scan == ScalarInput.ISV_KEY_RIGHT) {
            moveBy(STEP_SIZES[stepIndex]);
        } else if (scan == ScalarInput.ISV_KEY_LEFT) {
            moveBy(-STEP_SIZES[stepIndex]);
        } else if (scan == ScalarInput.ISV_KEY_UP) {
            stepIndex = Math.min(stepIndex + 1, STEP_SIZES.length - 1);
        } else if (scan == ScalarInput.ISV_KEY_DOWN) {
            stepIndex = Math.max(stepIndex - 1, 0);
        } else if (scan == ScalarInput.ISV_KEY_ENTER) {
            toggleFocusMode();
        } else if (scan == ScalarInput.ISV_KEY_S1_1) {
            autoFocus();
        } else if (scan == ScalarInput.ISV_KEY_S2) {
            takePicture();
        } else if (scan == ScalarInput.ISV_KEY_DELETE || scan == ScalarInput.ISV_KEY_SK2) {
            return true;
        } else {
            return super.onKeyDown(keyCode, event);
        }
        refresh();
        return true;
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        int scan = event.getScanCode();
        if (scan == ScalarInput.ISV_KEY_DELETE || scan == ScalarInput.ISV_KEY_SK2) {
            finish();
            return true;
        }
        if (scan == ScalarInput.ISV_KEY_S2 && camera != null) {
            camera.cancelTakePicture();
            return true;
        }
        return isHandled(scan) || super.onKeyUp(keyCode, event);
    }

    private static boolean isHandled(int scan) {
        return scan == ScalarInput.ISV_KEY_RIGHT || scan == ScalarInput.ISV_KEY_LEFT
                || scan == ScalarInput.ISV_KEY_UP || scan == ScalarInput.ISV_KEY_DOWN
                || scan == ScalarInput.ISV_KEY_ENTER || scan == ScalarInput.ISV_KEY_S1_1
                || scan == ScalarInput.ISV_KEY_S2;
    }

    /** Moves the target offset by delta (clamped to the camera's window) and sends it. */
    private void moveBy(int delta) {
        if (camera == null) return;
        if (pendingSince != 0) {
            lastResult = "busy: shift still running";
            return;
        }
        final int target = Math.max(MIN_OFFSET, Math.min(MAX_OFFSET, offset + delta));
        if (target == offset) {
            lastResult = "at window limit (" + offset + ")";
            Logger.info(lastResult);
            return;
        }
        if (!armed) {
            // Without a prior autofocus, shiftFocusPosition never returns and freezes the camera.
            autoFocus();
            lastResult = "arming (autofocus), then shift(" + target + ")";
            ticker.postDelayed(new Runnable() {
                public void run() { shift(target); }
            }, ARM_DELAY_MS);
            return;
        }
        shift(target);
    }

    /**
     * Runs shiftFocusPosition on a worker thread: from the UI thread the call never returns.
     * One call at a time; the overlay shows how long it has run, and a hang is logged.
     */
    private void shift(final int target) {
        if (camera == null || pendingSince != 0) return;
        final CameraEx cam = camera;
        final int steps = target;
        calls++;
        hangLogged = false;
        pendingSince = System.currentTimeMillis();
        lastResult = "shift(" + steps + ") running...";
        Logger.info("shift(" + steps + ") calling | offset " + offset + " | focus-mode " + focusMode() + " | armed " + armed);
        new Thread(new Runnable() {
            public void run() {
                String result;
                boolean ok = false;
                try {
                    ok = cam.shiftFocusPosition(steps);
                    result = "shift(" + steps + ") -> " + ok;
                } catch (Throwable t) {
                    result = "shift(" + steps + ") threw " + t;
                }
                final long ms = System.currentTimeMillis() - pendingSince;
                final boolean success = ok;
                final String message = result + " in " + ms + " ms";
                Logger.info(message);
                runOnUiThread(new Runnable() {
                    public void run() {
                        pendingSince = 0;
                        if (success) {
                            offset = target;
                        } else {
                            failures++;
                        }
                        lastResult = message;
                        refresh();
                    }
                });
            }
        }, "focus-shift").start();
        ticker.postDelayed(tick, 500);
    }

    private final android.os.Handler ticker = new android.os.Handler();
    private final Runnable tick = new Runnable() {
        public void run() {
            if (pendingSince == 0) return;
            long ms = System.currentTimeMillis() - pendingSince;
            lastResult = "shift running for " + (ms / 1000) + " s...";
            if (ms > HANG_MS && !hangLogged) {
                hangLogged = true;
                Logger.info("HANG: shift still running after " + ms + " ms | armed " + armed);
            }
            refresh();
            ticker.postDelayed(this, 500);
        }
    };

    private void toggleFocusMode() {
        if (camera == null) return;
        try {
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            // Cycle auto -> dmf -> manual (focus-mode-values on the NEX-5R: manual,auto,dmf).
            String current = params.getFocusMode();
            String next = "auto".equals(current) ? "dmf" : "dmf".equals(current) ? "manual" : "auto";
            params.setFocusMode(next);
            camera.getNormalCamera().setParameters(params);
            lastResult = "focus-mode -> " + focusMode();
        } catch (Throwable t) {
            lastResult = "focus-mode change threw " + t;
        }
        Logger.info(lastResult);
    }

    private void autoFocus() {
        if (camera == null) return;
        try {
            camera.getNormalCamera().autoFocus(null);
            armed = true;
            // Assumption under test: AF makes the current lens position the new reference (offset 0).
            offset = 0;
            lastResult = "autofocus in " + focusMode() + " (armed, offset reset to 0)";
        } catch (Throwable t) {
            lastResult = "autofocus threw " + t;
        }
        Logger.info(lastResult);
    }

    private void takePicture() {
        if (camera == null) return;
        try {
            camera.getNormalCamera().takePicture(null, null, null);
            lastResult = "picture at offset " + offset;
        } catch (Throwable t) {
            lastResult = "takePicture threw " + t;
        }
        Logger.info(lastResult);
    }

    private String focusMode() {
        try {
            return camera.getNormalCamera().getParameters().getFocusMode();
        } catch (Throwable t) {
            return "?";
        }
    }

    private void refresh() {
        overlay.setText("FOCUS TEST\n"
                + "Offset: " + offset + " (window " + MIN_OFFSET + ".." + MAX_OFFSET + ")   Step: " + STEP_SIZES[stepIndex] + "\n"
                + "Focus mode: " + (camera == null ? "-" : focusMode()) + "   Armed: " + armed + "\n"
                + "Calls: " + calls + "   Failed: " + failures + "\n"
                + lastResult + "\n\n"
                + "</> move  ^/v step  OK mode\n"
                + "half-press AF  shutter photo  trash exit");
    }

    /** Tells the camera which app is in front, as PMCADemo does; without it key handling can misbehave. */
    private void notifyAppInfo() {
        Intent intent = new Intent("com.android.server.DAConnectionManagerService.AppInfoReceive");
        intent.putExtra("package_name", getComponentName().getPackageName());
        intent.putExtra("class_name", getComponentName().getClassName());
        sendBroadcast(intent);
    }
}
