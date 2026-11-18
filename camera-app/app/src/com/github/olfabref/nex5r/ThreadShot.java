package com.github.olfabref.nex5r;

import android.hardware.Camera;
import android.os.Environment;
import android.os.Handler;
import android.os.HandlerThread;
import android.view.SurfaceHolder;

import com.sony.scalar.hardware.CameraEx;

import java.io.File;

/**
 * Software shot with the camera owned by a dedicated HandlerThread, as Sony's base apps do (Smart Remote
 * and Time-lapse open the camera and call autoFocus / burstableTakePicture on the "ExecutorCreator"
 * HandlerThread, never on the UI thread). The caller must release its own UI-thread camera first.
 *
 * Sequence (Smart Remote's, from its logcat on 2026-11-18): open, preview on, Camera.autoFocus(cb),
 * then burstableTakePicture (or takePicture), cancelTakePicture after `seconds`, cancelAutoFocus at
 * onShutter. The camera stays open on the thread until {@link #release()}.
 */
final class ThreadShot {
    private HandlerThread thread;
    private Handler handler;
    private CameraEx camera;
    private long t0;

    boolean isOpen() { return camera != null; }

    private void ensureThread() {
        if (thread == null) {
            thread = new HandlerThread("ThreadShot");
            thread.start();
            handler = new Handler(thread.getLooper());
        }
    }

    /** camthread mode: opens the camera and starts the preview on the thread, from surfaceCreated. */
    void openWithPreview(final SurfaceHolder holder) {
        ensureThread();
        handler.post(new Runnable() {
            public void run() {
                t0 = System.currentTimeMillis();
                if (camera != null) return;
                try {
                    open(holder);
                } catch (Throwable t) {
                    log("open on thread threw " + t);
                }
            }
        });
    }

    /** Opens the camera on the thread (first call) and runs one shot. Returns at once. */
    String shoot(final SurfaceHolder holder, final int seconds, final boolean af, final boolean burst) {
        ensureThread();
        handler.post(new Runnable() {
            public void run() {
                t0 = System.currentTimeMillis();
                try {
                    if (camera == null) open(holder);
                } catch (Throwable t) {
                    log("open on thread threw " + t);
                    return;
                }
                handler.postDelayed(new Runnable() {
                    public void run() { fire(seconds, af, burst); }
                }, 1500);
            }
        });
        return "threadshot: opening on thread " + thread.getName() + ", shot in 1.5 s (af=" + af
                + ", burst=" + burst + "), close after " + seconds + " s; see /log";
    }

    private void open(SurfaceHolder holder) throws Exception {
        camera = MainActivity.openCameraEx();
        log("CameraEx.open on thread " + Thread.currentThread().getName());
        camera.setShutterListener(new CameraEx.ShutterListener() {
            public void onShutter(int status, CameraEx c) {
                log("onShutter status " + status + " (thread " + Thread.currentThread().getName() + ")");
                try {
                    camera.getNormalCamera().cancelAutoFocus();
                } catch (Throwable t) {
                    log("cancelAutoFocus threw " + t);
                }
            }
        });
        Camera n = camera.getNormalCamera();
        Camera.Parameters p = n.getParameters();
        try {
            android.util.Pair<?, ?> ss = camera.createParametersModifier(p).getShutterSpeed();
            log("settings: scene-mode " + p.getSceneMode() + " | focus " + p.getFocusMode()
                    + " | shutter " + ss.first + "/" + ss.second);
        } catch (Throwable t) {
            log("settings threw " + t);
        }
        // 2026-11-18: startPreview failed here once (surface handed over from the UI-thread camera?);
        // shoot anyway, the outcome without preview is informative too.
        try {
            if (holder != null) n.setPreviewDisplay(holder);
            n.startPreview();
            log("startPreview on thread ok");
        } catch (Throwable t) {
            log("preview on thread failed, shooting without: " + t);
        }
    }

    private void fire(final int seconds, boolean af, boolean burst) {
        final long since = System.currentTimeMillis() - 2000;
        try {
            if (af) {
                camera.getNormalCamera().autoFocus(new Camera.AutoFocusCallback() {
                    public void onAutoFocus(boolean ok, Camera c) { log("onAutoFocus " + ok); }
                });
                log("autoFocus(cb) called");
            }
            if (burst) camera.burstableTakePicture(); else camera.getNormalCamera().takePicture(null, null, null);
            log((burst ? "burstableTakePicture" : "takePicture") + " called");
        } catch (Throwable t) {
            log("shot threw " + t);
            return;
        }
        handler.postDelayed(new Runnable() {
            public void run() {
                try {
                    camera.cancelTakePicture();
                    log("cancelTakePicture called");
                } catch (Throwable t) {
                    log("cancelTakePicture threw " + t);
                }
                handler.postDelayed(new Runnable() {
                    public void run() { log("newest DCIM file: " + newest()); }
                }, 5000);
            }
        }, seconds * 1000L);
    }

    void release() {
        if (handler == null) return;
        handler.post(new Runnable() {
            public void run() {
                if (camera != null) {
                    camera.release();
                    camera = null;
                }
            }
        });
        thread.quit();
        thread = null;
        handler = null;
    }

    private void log(String what) {
        Logger.info("[threadshot t+" + (System.currentTimeMillis() - t0) + " ms] " + what);
    }

    private static String newest() {
        File best = null;
        File[] dirs = new File(Environment.getExternalStorageDirectory(), "DCIM").listFiles();
        if (dirs != null) {
            for (File d : dirs) {
                File[] files = d.listFiles();
                if (files == null) continue;
                for (File f : files) {
                    if (best == null || f.getName().compareTo(best.getName()) > 0) best = f;
                }
            }
        }
        return best == null ? "-" : best.getName();
    }
}
