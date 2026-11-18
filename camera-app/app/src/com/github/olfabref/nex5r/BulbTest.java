package com.github.olfabref.nex5r;

import android.hardware.Camera;
import android.os.Environment;
import android.os.Handler;
import android.util.Pair;

import com.sony.scalar.hardware.CameraEx;

import java.io.File;

/**
 * Bulb test: can an embedded app make a timed long exposure?
 *
 * Plan: switch to manual exposure (scene-mode "manual-exposure"), step the shutter speed past 30"
 * until the camera reports Bulb, then takePicture() and cancelTakePicture() N seconds later,
 * which is what pressing and releasing the shutter button does. Every Sony callback is logged
 * with its time since the start of the exposure, plus the new files in DCIM.
 *
 * Nothing here is known to exist on the NEX-5R firmware: every Sony call catches Throwable
 * (a missing method is a NoSuchMethodError) and logs it.
 */
final class BulbTest {
    private static final int[] DURATIONS_S = {5, 10, 30, 60, 120, 300};
    /** getShutterSpeed() past 30" on the NEX-5R (fw 1.03): 65535/1, presumably Bulb. */
    private static final String BULB = "65535/1";

    private final Handler handler;
    private final Runnable onChange;
    private CameraEx camera;

    private int durationIndex = 1;
    private String shutterSpeed = "?";
    private String lastResult = "-";
    private long exposureStart = 0;   // 0 when no exposure is running
    private long exposureEnd = 0;     // when cancelTakePicture was called

    BulbTest(Handler handler, Runnable onChange) {
        this.handler = handler;
        this.onChange = onChange;
    }

    /** Called once the camera is open: installs the listeners and logs the exposure settings. */
    void attach(CameraEx cam) {
        camera = cam;
        try {
            cam.setShutterSpeedChangeListener(new CameraEx.ShutterSpeedChangeListener() {
                public void onShutterSpeedChange(CameraEx.ShutterSpeedInfo i, CameraEx c) {
                    shutterSpeed = i.currentShutterSpeed_n + "/" + i.currentShutterSpeed_d;
                    Logger.info("onShutterSpeedChange: current " + shutterSpeed
                            + " | available " + i.currentAvailableMin_n + "/" + i.currentAvailableMin_d
                            + " .. " + i.currentAvailableMax_n + "/" + i.currentAvailableMax_d);
                    onChange.run();
                }
            });
        } catch (Throwable t) {
            Logger.error("setShutterSpeedChangeListener", t);
        }
        try {
            cam.setShutterListener(new CameraEx.ShutterListener() {
                public void onShutter(int status, CameraEx c) {
                    event("onShutter status " + status + " (ok " + CameraEx.ShutterListener.STATUS_OK
                            + ", canceled " + CameraEx.ShutterListener.STATUS_CANCELED
                            + ", error " + CameraEx.ShutterListener.STATUS_ERROR + ")");
                }
            });
        } catch (Throwable t) {
            Logger.error("setShutterListener", t);
        }
        try {
            cam.setCaptureStatusListener(new CameraEx.OnCaptureStatusListener() {
                public void onStart(int a, CameraEx c) { event("onCaptureStatus start " + a); }

                public void onEnd(int a, int reason, CameraEx c) {
                    event("onCaptureStatus end " + a + " reason " + reason + " (normal 1, cancel 2)");
                }
            });
        } catch (Throwable t) {
            Logger.info("setCaptureStatusListener unavailable: " + t);
        }
        try {
            cam.setExposureCompleteListener(new CameraEx.ExposureCompleteListener() {
                public void onDone(int status, CameraEx.ExposureInfo i, CameraEx c) {
                    event("onExposureComplete status " + status + " | shutter "
                            + i.ShutterSpeedNumber + "/" + i.ShutterSpeedDeanom
                            + " | F " + i.FNo + " | ISO " + i.IsoSpeedRate);
                }
            });
        } catch (Throwable t) {
            Logger.info("setExposureCompleteListener unavailable: " + t);
        }
        try {
            cam.setStoreImageCompleteListener(new CameraEx.StoreImageCompleteListener() {
                public void onDone(int status, CameraEx.StoreImageInfo i, CameraEx c) {
                    event("onStoreImageComplete status " + status);
                    logNewFiles();
                    exposureStart = 0;
                    onChange.run();
                }
            });
        } catch (Throwable t) {
            Logger.info("setStoreImageCompleteListener unavailable: " + t);
        }
        // Smart Remote's BaseShootingExecutor.prepare installs these three before any shot.
        try {
            cam.setAutoFocusStartListener(new CameraEx.AutoFocusStartListener() {
                public void onStart(CameraEx c) { event("onAutoFocusStart"); }
            });
            cam.setAutoFocusDoneListener(new CameraEx.AutoFocusDoneListener() {
                public void onDone(int status, int[] areas, CameraEx c) {
                    event("onAutoFocusDone status " + status);
                    Runnable r = pendingOpen;
                    pendingOpen = null;
                    if (r != null) handler.post(r);
                }
            });
            cam.setPreviewStartListener(new CameraEx.PreviewStartListener() {
                public void onStart(CameraEx c) { event("onPreviewStart"); }
            });
            Logger.info("AF start/done and preview start listeners set");
        } catch (Throwable t) {
            Logger.info("AF/preview listeners unavailable: " + t);
        }
        try {
            // TimeLapse installs one before shooting from code.
            reviewControl = new CameraEx.AutoPictureReviewControl();
            cam.setAutoPictureReviewControl(reviewControl);
            Logger.info("AutoPictureReviewControl set, review time " + reviewControl.getPictureReviewTime());
        } catch (Throwable t) {
            Logger.info("setAutoPictureReviewControl unavailable: " + t);
        }
        logSettings("attach");
    }

    void detach() {
        try {
            if (camera != null && reviewControl != null) camera.setAutoPictureReviewControl(null);
        } catch (Throwable t) {
            // releasing anyway
        }
        reviewControl = null;
        handler.removeCallbacks(endExposure);
        handler.removeCallbacks(tick);
        camera = null;
        exposureStart = 0;
    }

    boolean isExposing() { return exposureStart != 0; }

    /** Switches to manual exposure and single shot, the only mode where Bulb can exist. */
    void enterManualExposure() {
        if (camera == null) return;
        try {
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            Logger.info("scene-mode was " + params.getSceneMode() + ", values " + params.get("scene-mode-values"));
            params.setSceneMode(CameraEx.ParametersModifier.SCENE_MODE_MANUAL_EXPOSURE);
            try {
                camera.createParametersModifier(params).setDriveMode(CameraEx.ParametersModifier.DRIVE_MODE_SINGLE);
            } catch (Throwable t) {
                Logger.error("setDriveMode(single)", t);
            }
            camera.getNormalCamera().setParameters(params);
            lastResult = "scene-mode -> " + camera.getNormalCamera().getParameters().getSceneMode();
        } catch (Throwable t) {
            lastResult = "manual exposure threw " + t;
        }
        Logger.info(lastResult);
        logSettings("after manual exposure");
    }

    /** Remote control mode (IR remote?): may let the camera release without the shutter button. */
    String setRemoteControlMode(boolean on) {
        if (camera == null) return "no camera";
        String r;
        try {
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            CameraEx.ParametersModifier m = camera.createParametersModifier(params);
            r = "supported " + m.isSupportedRemoteControlMode() + ", was " + m.getRemoteControlMode();
            m.setRemoteControlMode(on);
            camera.getNormalCamera().setParameters(params);
            r += ", now " + camera.createParametersModifier(camera.getNormalCamera().getParameters()).getRemoteControlMode();
        } catch (Throwable t) {
            r = "remote control mode threw " + t;
        }
        Logger.info("setRemoteControlMode(" + on + "): " + r);
        return r;
    }

    /** One shutter speed step: slower (towards Bulb) or faster. */
    void stepShutter(boolean slower) {
        if (camera == null || isExposing()) return;
        try {
            // Which direction is "slower" is a guess: the log of onShutterSpeedChange tells.
            if (slower) camera.decrementShutterSpeed(); else camera.incrementShutterSpeed();
            lastResult = (slower ? "decrementShutterSpeed" : "incrementShutterSpeed") + " called";
        } catch (Throwable t) {
            lastResult = "shutter step threw " + t;
        }
        Logger.info(lastResult);
        handler.postDelayed(new Runnable() {
            public void run() { logSettings("after shutter step"); onChange.run(); }
        }, 300);
    }

    void stepDuration(int delta) {
        durationIndex = Math.max(0, Math.min(DURATIONS_S.length - 1, durationIndex + delta));
    }

    void toggleLongExposureNR() {
        if (camera == null) return;
        try {
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            CameraEx.ParametersModifier m = camera.createParametersModifier(params);
            if (!m.isSupportedLongExposureNR()) {
                lastResult = "long exposure NR not supported";
            } else {
                m.setLongExposureNR(!m.getLongExposureNR());
                camera.getNormalCamera().setParameters(params);
                lastResult = "long exposure NR -> " + longExposureNR();
            }
        } catch (Throwable t) {
            lastResult = "NR toggle threw " + t;
        }
        Logger.info(lastResult);
    }

    /** Opens the shutter and schedules the close: the timed equivalent of holding the shutter button. */
    void startExposure() { startExposure(DURATIONS_S[durationIndex], "normal", false); }

    /**
     * Same, with an explicit duration and opening method (HTTP /capture). Must run on the UI thread.
     * Methods: "normal" = Camera.takePicture, "burstable" = CameraEx.burstableTakePicture,
     * "direct" = CameraEx.startDirectShutter (closed with stopDirectShutter). The others close with
     * cancelTakePicture. af = run autoFocus first (in focus-mode manual it does not move the lens).
     *
     * Known on the NEX-5R: "normal" from a key handler right after a physical half-press works; from
     * HTTP it never opens the shutter (onShutter "canceled" only at cancelTakePicture, no file), and
     * the software autoFocus never calls back.
     */
    String startExposure(int seconds, String method, boolean af) {
        if (camera == null) return "no camera";
        if (isExposing()) return "busy: exposure running";
        if (!java.util.Arrays.asList("normal", "burstable", "direct", "dnormal", "dburst").contains(method)
                && !"afnormal".equals(method) && !"afburst".equals(method)) {
            return "unknown method " + method;
        }
        logSettings("before exposure");
        exposureEnd = 0;
        exposureStart = System.currentTimeMillis();
        this.method = method;
        if (method.startsWith("d") && !"direct".equals(method)) {
            // Direct shutter as a mode (as TimeLapse seems to do): start it, then shoot with takePicture /
            // burstableTakePicture; stopDirectShutter after the close.
            try {
                camera.startDirectShutter();
                event("startDirectShutter called (mode)");
            } catch (Throwable t) {
                event("startDirectShutter threw " + t);
            }
            final int s0 = seconds;
            handler.postDelayed(new Runnable() {
                public void run() { open(s0); }
            }, 1000);
            lastResult = "BULB " + seconds + " s: direct mode, opening in 1 s";
            return lastResult;
        }
        if (method.startsWith("af")) {
            // Mimic the key flow that works: half-press (autoFocus(null)) then the shot at once, no wait.
            try {
                camera.getNormalCamera().autoFocus(null);
                event("autoFocus(null) then open at once");
            } catch (Throwable t) {
                event("autoFocus threw " + t);
            }
            open(seconds);
            return lastResult;
        }
        if (!af) {
            open(seconds);
            return lastResult;
        }
        final int s = seconds;
        final boolean[] opened = {false};
        final Runnable open = new Runnable() {
            public void run() {
                if (opened[0] || camera == null) return;
                opened[0] = true;
                open(s);
            }
        };
        pendingOpen = open;
        try {
            camera.getNormalCamera().autoFocus(new Camera.AutoFocusCallback() {
                public void onAutoFocus(boolean success, Camera c) {
                    event("onAutoFocus " + success);
                    handler.post(open);
                }
            });
            event("autoFocus called before exposure");
        } catch (Throwable t) {
            event("autoFocus threw " + t);
        }
        handler.postDelayed(new Runnable() {
            public void run() {
                if (!opened[0]) event("no onAutoFocus after 3 s, opening anyway");
                open.run();
            }
        }, 3000);
        lastResult = "BULB " + seconds + " s: focusing";
        return lastResult;
    }

    private String method = "normal";
    private volatile Runnable pendingOpen;   // run by onAutoFocusDone (af=1)
    private CameraEx.AutoPictureReviewControl reviewControl;

    private void open(int seconds) {
        exposureStart = System.currentTimeMillis();
        try {
            if ("burstable".equals(method) || "dburst".equals(method) || "afburst".equals(method)) {
                camera.burstableTakePicture();
            } else if ("direct".equals(method)) {
                try {
                    Logger.info("isDirectShutterSupported " + camera.createParametersModifier(
                            camera.getNormalCamera().getParameters()).isDirectShutterSupported());
                } catch (Throwable t) {
                    Logger.info("isDirectShutterSupported threw " + t);
                }
                camera.startDirectShutter();
            } else {
                camera.getNormalCamera().takePicture(null, null, null);
            }
            boolean bulb = BULB.equals(shutterSpeed);
            lastResult = (bulb ? "BULB exposing " + seconds + " s" : "NOT BULB: shutter " + shutterSpeed + ", duration ignored")
                    + " (" + method + ")";
            Logger.info(method + " open called at shutter " + shutterSpeed + (bulb ? " (bulb)" : " (NOT bulb)")
                    + ", close in " + seconds + " s");
            handler.postDelayed(endExposure, seconds * 1000L);
            handler.postDelayed(tick, 1000);
        } catch (Throwable t) {
            exposureStart = 0;
            lastResult = method + " open threw " + t;
            Logger.info(lastResult);
        }
        onChange.run();
    }

    /** Lists the DCIM files 3 s and 10 s from now (for the keyshoot=0 test). */
    void checkFilesLater() {
        final long since = System.currentTimeMillis() - 2000;
        lastResult = "S2 ignored by the app, checking DCIM";
        onChange.run();
        handler.postDelayed(new Runnable() {
            public void run() { listFiles(since, "keyshoot off, files 3 s after S2"); }
        }, 3000);
        handler.postDelayed(new Runnable() {
            public void run() { listFiles(since, "keyshoot off, files 10 s after S2"); }
        }, 10000);
    }

    /** One line per field, for HTTP /status. */
    String state() {
        return "shutter=" + shutterSpeed + "\nbulb=" + BULB.equals(shutterSpeed) + "\nexposing=" + isExposing()
                + "\ninhibition=" + inhibition() + "\nlast=" + lastResult + "\n";
    }

    /** CameraEx.getInhibitionInfo() (Sony logs it as "the factor" when a setting fails), or the error. */
    private String inhibition() {
        if (camera == null) return "-";
        try {
            return String.valueOf(camera.getInhibitionInfo());
        } catch (Throwable t) {
            return "? " + t;
        }
    }

    private final Runnable endExposure = new Runnable() {
        public void run() {
            if (camera == null || exposureStart == 0) return;
            exposureEnd = System.currentTimeMillis();
            try {
                if ("direct".equals(method)) {
                    camera.stopDirectShutter(new CameraEx.DirectShutterStoppedCallback() {
                        public void onShutterStopped(CameraEx c) { event("onShutterStopped"); }
                    });
                    event("stopDirectShutter called");
                } else {
                    camera.cancelTakePicture();
                    event("cancelTakePicture called");
                    if (method.startsWith("d")) {
                        camera.stopDirectShutter(new CameraEx.DirectShutterStoppedCallback() {
                            public void onShutterStopped(CameraEx c) { event("onShutterStopped (mode)"); }
                        });
                    }
                }
            } catch (Throwable t) {
                event("close threw " + t);
            }
            // onStoreImageComplete does not exist on the NEX-5R: poll DCIM instead, then free the page.
            final long since = exposureStart - 2000;
            handler.postDelayed(new Runnable() {
                public void run() { listFiles(since, "new files 3 s after close"); }
            }, 3000);
            handler.postDelayed(new Runnable() {
                public void run() {
                    listFiles(since, "new files 15 s after close");
                    exposureStart = 0;
                    lastResult = "done, see LOG.TXT (new files)";
                    onChange.run();
                }
            }, 15000);
            onChange.run();
        }
    };

    private final Runnable tick = new Runnable() {
        public void run() {
            if (exposureStart == 0) return;
            long s = (System.currentTimeMillis() - exposureStart) / 1000;
            lastResult = (exposureEnd == 0 ? (BULB.equals(shutterSpeed) ? "BULB exposing: " : "NOT BULB, waiting: ")
                    : "closed, waiting for the file: ") + s + " s";
            onChange.run();
            handler.postDelayed(this, 1000);
        }
    };

    private void event(String what) {
        long t = exposureStart == 0 ? -1 : System.currentTimeMillis() - exposureStart;
        lastResult = what;
        Logger.info("[t+" + t + " ms] " + what);
        onChange.run();
    }

    /** Logs the files in DCIM written since the exposure started (JPG and/or ARW, with sizes). */
    private void logNewFiles() {
        final long since = exposureStart - 2000;
        // The file may still be growing when the listener fires: list it now and 5 s later.
        listFiles(since, "new files");
        handler.postDelayed(new Runnable() {
            public void run() { listFiles(since, "new files 5 s later"); }
        }, 5000);
    }

    private static void listFiles(long since, String label) {
        File dcim = new File(Environment.getExternalStorageDirectory(), "DCIM");
        StringBuilder out = new StringBuilder(label + ":");
        File[] dirs = dcim.listFiles();
        if (dirs != null) {
            for (File dir : dirs) {
                File[] files = dir.listFiles();
                if (files == null) continue;
                for (File f : files) {
                    if (f.lastModified() >= since) out.append(' ').append(dir.getName()).append('/').append(f.getName())
                            .append(" (").append(f.length()).append(" B)");
                }
            }
        }
        Logger.info(out.toString());
    }

    private void logSettings(String when) {
        if (camera == null) return;
        try {
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            CameraEx.ParametersModifier m = camera.createParametersModifier(params);
            Pair<?, ?> ss = m.getShutterSpeed();
            shutterSpeed = ss == null ? "null" : ss.first + "/" + ss.second;
            Logger.info("settings (" + when + "): scene-mode " + params.getSceneMode()
                    + " | shutter " + shutterSpeed + " | ISO " + m.getISOSensitivity()
                    + " | drive " + m.getDriveMode() + " | long-exposure-NR " + longExposureNR()
                    + " | inhibition " + inhibition());
        } catch (Throwable t) {
            Logger.error("logSettings (" + when + ")", t);
        }
    }

    private String longExposureNR() {
        try {
            CameraEx.ParametersModifier m = camera.createParametersModifier(camera.getNormalCamera().getParameters());
            return m.isSupportedLongExposureNR() ? String.valueOf(m.getLongExposureNR()) : "unsupported";
        } catch (Throwable t) {
            return "?";
        }
    }

    String status() {
        return "BULB TEST\n"
                + "Shutter: " + (BULB.equals(shutterSpeed) ? "BULB" : shutterSpeed) + "   Duration: " + DURATIONS_S[durationIndex] + " s\n"
                + "Long exposure NR: " + (camera == null ? "-" : longExposureNR()) + "\n"
                + lastResult + "\n\n"
                + "</> shutter speed  ^/v duration  OK NR\n"
                + "shutter: timed exposure  SK1 focus page  trash exit";
    }
}
