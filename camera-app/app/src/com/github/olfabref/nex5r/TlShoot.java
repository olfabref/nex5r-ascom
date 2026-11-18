package com.github.olfabref.nex5r;

import android.content.Context;
import android.content.Intent;
import android.hardware.Camera;
import android.os.Environment;
import android.os.Handler;
import android.view.SurfaceHolder;

import com.sony.scalar.hardware.CameraEx;
import com.sony.scalar.sysutil.didep.Gpelibrary;

import java.io.File;

/**
 * One software shot with TimeLapse 1.4.0's sequence (jonasjuffinger/TimeLapse, ShootActivity +
 * pmcademo BaseActivity), which DOES fire on this NEX-5R (2026-11-18) where all our attempts were
 * canceled. Options (HTTP /tlshoot query, all default to TimeLapse's defaults) to find which step matters:
 *
 *   ael=1       ParametersModifier.setAutoExposureLock(AE_LOCK_ON)
 *   mf=1        focus mode manual (0: "auto")
 *   drive=bracket|single  bracket = 3-shot exposure bracket (TimeLapse default brs=true)
 *   silent=1    setSilentShutterMode
 *   review=1    AutoPictureReviewControl
 *   params=1    setParameters(params) with the above (0: skip all parameter changes)
 *   startpreview=0  1: also call startPreview() ourselves (TimeLapse only sets the preview display)
 *   apo=1       broadcast APO/NO;  gpe=1  Gpelibrary ABGR8888;  appinfo=1  plain notifyAppInfo
 *   delay=3     seconds from onResume to burstableTakePicture (main-thread Handler, as TimeLapse)
 *
 * cancelTakePicture runs in onShutter, as in TimeLapse. Runs inside MainActivity (a second activity
 * dropped Wi-Fi and crashed, 2026-11-18): MainActivity releases its own camera first, then calls
 * {@link #start}; the camera stays with TlShoot until {@link #release()}. Results go to NEX5R/LOG.TXT.
 * All calls on the UI thread.
 */
final class TlShoot implements CameraEx.ShutterListener {
    private final Context context;
    private final Handler handler = new Handler();
    private CameraEx cameraEx;
    private String opts = "";
    private long t0;
    private int shutters;
    private String before;

    TlShoot(Context context) { this.context = context; }

    boolean isOpen() { return cameraEx != null; }

    /** Opens the camera TimeLapse's way on the given (already created) surface and shoots after delay. */
    String start(String options, SurfaceHolder holder) {
        release();
        opts = options == null ? "" : options;
        t0 = System.currentTimeMillis();
        shutters = 0;
        before = newest();
        log("=== tlshoot start, opts '" + opts + "', newest DCIM " + before);
        try {
            if (on("gpe", true)) Gpelibrary.changeFrameBufferPixel(Gpelibrary.GS_FRAMEBUFFER_TYPE.ABGR8888);
        } catch (Throwable t) {
            log("Gpelibrary threw " + t);
        }
        if (on("appinfo", true)) {
            Intent i = new Intent("com.android.server.DAConnectionManagerService.AppInfoReceive");
            i.putExtra("package_name", context.getPackageName());
            i.putExtra("class_name", MainActivity.class.getName());
            context.sendBroadcast(i);
        }

        try {
            cameraEx = CameraEx.open(0, null);
            cameraEx.setShutterListener(this);
            if (on("review", true)) cameraEx.setAutoPictureReviewControl(new CameraEx.AutoPictureReviewControl());
            if (on("params", true)) configure();
            preview(holder);
        } catch (Throwable t) {
            log("open/configure threw " + t);
            return "tlshoot: open/configure threw " + t;
        }
        if (on("apo", true)) apo(false);

        int delay = num("delay", 3);
        handler.postDelayed(new Runnable() {
            public void run() { shoot(); }
        }, delay * 1000L);
        handler.postDelayed(new Runnable() {
            public void run() { report(); }
        }, (delay + 12) * 1000L);
        return "tlshoot: shot in " + delay + " s (opts '" + opts + "'), result in /log ~" + (delay + 12) + " s";
    }

    private void configure() {
        Camera.Parameters params = cameraEx.getNormalCamera().getParameters();
        try {
            params.setFocusMode(on("mf", true) ? CameraEx.ParametersModifier.FOCUS_MODE_MANUAL : "auto");
        } catch (Throwable t) {
            log("setFocusMode threw " + t);
        }
        CameraEx.ParametersModifier m = cameraEx.createParametersModifier(params);
        boolean bracket = !"single".equals(str("drive", "bracket"));
        try {
            if (bracket) {
                m.setDriveMode(CameraEx.ParametersModifier.DRIVE_MODE_BRACKET);
                m.setBracketMode(CameraEx.ParametersModifier.BRACKET_MODE_EXPOSURE);
                m.setExposureBracketMode(CameraEx.ParametersModifier.EXPOSURE_BRACKET_MODE_SINGLE);
                m.setExposureBracketPeriod(30);
                m.setNumOfBracketPicture(3);
            } else {
                m.setDriveMode(CameraEx.ParametersModifier.DRIVE_MODE_SINGLE);
            }
        } catch (Throwable t) {
            log("drive mode threw " + t);
        }
        try {
            m.setSilentShutterMode(on("silent", true));
        } catch (Throwable t) {
            log("setSilentShutterMode threw " + t);
        }
        try {
            if (on("ael", true)) m.setAutoExposureLock(CameraEx.ParametersModifier.AE_LOCK_ON);
        } catch (Throwable t) {
            log("setAutoExposureLock threw " + t);
        }
        try {
            cameraEx.getNormalCamera().setParameters(params);
            log("setParameters ok (focus " + params.getFocusMode() + ", drive " + (bracket ? "bracket" : "single") + ")");
        } catch (Throwable t) {
            log("setParameters threw " + t);
        }
    }

    private void shoot() {
        if (cameraEx == null) return;
        log("calling burstableTakePicture");
        try {
            cameraEx.burstableTakePicture();
            log("burstableTakePicture called");
        } catch (Throwable t) {
            log("burstableTakePicture threw " + t);
        }
    }

    public void onShutter(int status, CameraEx c) {
        shutters++;
        log("onShutter status " + status + " (#" + shutters + ")");
        try {
            cameraEx.cancelTakePicture();
        } catch (Throwable t) {
            log("cancelTakePicture threw " + t);
        }
    }

    private void report() {
        String after = newest();
        log("=== tlshoot end: " + shutters + " onShutter, newest DCIM " + after
                + (after.equals(before) ? " (NO new file)" : " (NEW file)"));
    }

    void release() {
        handler.removeCallbacksAndMessages(null);
        if (cameraEx != null) {
            try {
                cameraEx.getNormalCamera().stopPreview();
                cameraEx.setAutoPictureReviewControl(null);
            } catch (Throwable ignored) {
            }
            cameraEx.release();
            cameraEx = null;
            if (on("apo", true)) apo(true);
        }
    }

    private void preview(SurfaceHolder h) {
        try {
            log("setPreviewDisplay (surface valid " + h.getSurface().isValid() + ")");
            cameraEx.getNormalCamera().setPreviewDisplay(h);
            log("setPreviewDisplay ok");
            if (on("startpreview", false)) {
                cameraEx.getNormalCamera().startPreview();
                log("startPreview called");
            }
        } catch (Throwable t) {
            log("preview threw " + t);
        }
    }

    private void apo(boolean enable) {
        Intent i = new Intent("com.android.server.DAConnectionManagerService.apo");
        i.putExtra("apo_info", enable ? "APO/NORMAL" : "APO/NO");
        context.sendBroadcast(i);
    }

    private boolean on(String key, boolean def) {
        String v = str(key, null);
        return v == null ? def : "1".equals(v);
    }

    private int num(String key, int def) {
        try {
            return Integer.parseInt(str(key, String.valueOf(def)));
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private String str(String key, String def) {
        for (String kv : opts.split("&")) {
            int eq = kv.indexOf('=');
            if (eq > 0 && kv.substring(0, eq).equals(key)) return kv.substring(eq + 1);
        }
        return def;
    }

    private void log(String what) {
        Logger.info("[tlshoot t+" + (System.currentTimeMillis() - t0) + " ms] " + what);
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
