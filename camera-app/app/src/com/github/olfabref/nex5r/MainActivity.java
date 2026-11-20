package com.github.olfabref.nex5r;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.hardware.Camera;
import android.net.wifi.WifiManager;
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
 * Focus page: live view plus lens focus offsets through FocusControl (what the NEX-5R allows is
 * described there). HTTP /focus and /focusarm drive the same FocusControl.
 *
 * Left / right: move the target offset by -/+ step. Up / down: change step size.
 * Enter: cycle focus mode (auto, dmf, manual). Half-press: autofocus. Full press: take a picture.
 * Trash: exit. Every action is logged to NEX5R/LOG.TXT on the SD card.
 *
 * SK1 (or MENU) switches to the Bulb test page, see BulbTest. The app starts on that page.
 * The app turns Wi-Fi on and serves HttpServer on port 8080 while it runs.
 */
public class MainActivity extends Activity implements SurfaceHolder.Callback {
    private static final int[] STEP_SIZES = {1, 2, 4, 8, 16};

    private SurfaceHolder surfaceHolder;
    private TextView overlay;
    private DisplayManager displayManager;
    private CameraEx camera;
    private final ThreadShot threadShot = new ThreadShot();
    private final TlShoot tlShoot = new TlShoot(this);
    private com.sony.scalar.sysutil.didep.Caution caution;   // kept alive: holds the callback
    private int noIpTicks = 0;   // wifiWatch ticks (2 s) without an IP

    private int stepIndex = 0;
    private String lastResult = "-";   // focus page: last non-focus action (open, photo)
    private FocusControl focus;
    private final android.os.Handler ticker = new android.os.Handler();

    private BulbTest bulb;
    private volatile boolean keyShoots = true;
    private HttpServer http;
    private WifiManager wifi;
    private String ip = "-";
    private boolean bulbPage = true;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Logger.installCrashHandler();
        bulb = new BulbTest(ticker, new Runnable() {
            public void run() { refresh(); }
        });
        focus = new FocusControl(ticker);
        bulb.setFocusControl(focus);

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
        setAutoPowerOff(false);

        displayManager = DisplayManager.create(this);
        // Live view and UI overlay only show correctly together in low color depth (as in PMCADemo).
        displayManager.setColorDepth(DisplayManager.ColorDepth.LOW);

        DeviceInfo info = DeviceInfo.getInstance();
        Logger.info("=== Focus test start: " + info.getModel() + " fw " + info.getFirmwareVersion()
                + " api " + info.getApiVersion());

        if (camThread()) {
            // Test mode (HTTP /camthread): the camera belongs to ThreadShot's HandlerThread from the
            // start, as in Sony's apps; it is opened with the preview in surfaceCreated.
            Logger.info("camthread mode: camera left to the HandlerThread");
        } else try {
            camera = openCamera();
            Camera.Parameters params = camera.getNormalCamera().getParameters();
            Logger.info("Camera parameters: " + params.flatten());
            bulb.attach(camera);
            focus.attach(camera);
            if (bulbPage) bulb.enterManualExposure();
        } catch (Throwable t) {
            Logger.error("Opening the camera failed", t);
            lastResult = "camera open FAILED: " + t;
        }
        startNetwork();
        startAdb();
        surfaceHolder.addCallback(this);
        refresh();
    }

    @Override
    protected void onPause() {
        super.onPause();
        surfaceHolder.removeCallback(this);
        ticker.removeCallbacks(wifiWatch);
        if (http != null) {
            http.stop();
            http = null;
        }
        bulb.detach();
        focus.detach();
        if (camera != null) {
            camera.release();
            camera = null;
        }
        threadShot.release();
        tlShoot.release();
        if (displayManager != null) {
            displayManager.setColorDepth(DisplayManager.ColorDepth.HIGH);
            displayManager.release();
            displayManager = null;
        }
        setAutoPowerOff(true);
        Logger.info("=== Focus test end: offset " + focus.offset() + ", " + focus.calls() + " calls, "
                + focus.failures() + " failed");
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        if (camThread()) {
            threadShot.openWithPreview(holder);
            return;
        }
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
        if (scan == ScalarInput.ISV_KEY_S1_1 || scan == ScalarInput.ISV_KEY_S1_2 || scan == ScalarInput.ISV_KEY_S2) {
            Logger.info("key down scan " + scan + " keyCode " + keyCode + " device " + event.getDeviceId()
                    + " flags 0x" + Integer.toHexString(event.getFlags()));
        }
        if (event.getRepeatCount() > 0) {
            // Ignore auto-repeat so one press = one call.
            return isHandled(scan) || super.onKeyDown(keyCode, event);
        }
        if (scan == ScalarInput.ISV_KEY_SK1 || scan == ScalarInput.ISV_KEY_MENU) {
            bulbPage = !bulbPage;
            Logger.info("page -> " + (bulbPage ? "bulb" : "focus"));
            if (bulbPage) bulb.enterManualExposure();
        } else if (bulbPage && bulbKey(scan)) {
            // handled by the bulb page
        } else if (scan == ScalarInput.ISV_KEY_RIGHT) {
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
            Logger.info("unhandled key: scan " + scan + " keyCode " + keyCode);
            return super.onKeyDown(keyCode, event);
        }
        refresh();
        return true;
    }

    /** Bulb page keys; returns false for keys the page leaves to the focus test (half-press AF, exit). */
    private boolean bulbKey(int scan) {
        if (scan == ScalarInput.ISV_KEY_RIGHT) {
            bulb.stepShutter(true);
        } else if (scan == ScalarInput.ISV_KEY_LEFT) {
            bulb.stepShutter(false);
        } else if (scan == ScalarInput.ISV_KEY_UP) {
            bulb.stepDuration(1);
        } else if (scan == ScalarInput.ISV_KEY_DOWN) {
            bulb.stepDuration(-1);
        } else if (scan == ScalarInput.ISV_KEY_ENTER) {
            bulb.toggleLongExposureNR();
        } else if (scan == ScalarInput.ISV_KEY_S2) {
            if (keyShoots) {
                bulb.startExposure();
            } else {
                // Decisive test: does the firmware shoot by itself on a physical full press?
                Logger.info("S2 pressed, keyshoot off: app does NOT call takePicture");
                bulb.checkFilesLater();
            }
        } else {
            return false;
        }
        return true;
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        int scan = event.getScanCode();
        if (scan == ScalarInput.ISV_KEY_DELETE || scan == ScalarInput.ISV_KEY_SK2) {
            finish();
            return true;
        }
        if (scan == ScalarInput.ISV_KEY_S2 && camera != null && !bulbPage) {
            camera.cancelTakePicture();
            return true;
        }
        return isHandled(scan) || super.onKeyUp(keyCode, event);
    }

    private static boolean isHandled(int scan) {
        return scan == ScalarInput.ISV_KEY_RIGHT || scan == ScalarInput.ISV_KEY_LEFT
                || scan == ScalarInput.ISV_KEY_UP || scan == ScalarInput.ISV_KEY_DOWN
                || scan == ScalarInput.ISV_KEY_ENTER || scan == ScalarInput.ISV_KEY_S1_1
                || scan == ScalarInput.ISV_KEY_S2 || scan == ScalarInput.ISV_KEY_SK1
                || scan == ScalarInput.ISV_KEY_MENU;
    }

    /**
     * Moves the target offset by delta on a worker thread (shiftFocusPosition never returns on the UI
     * thread); arms first with an autofocus in the current mode if needed.
     */
    private void moveBy(final int delta) {
        if (camera == null) return;
        if (focus.isMoving()) {
            lastResult = "busy: shift still running";
            return;
        }
        new Thread(new Runnable() {
            public void run() {
                if (!focus.isArmed()) focus.arm("");
                focus.moveTo(focus.offset() + delta);
                ticker.post(new Runnable() {
                    public void run() { refresh(); }
                });
            }
        }, "focus-key").start();
        lastResult = "moving...";
    }

    /** Runs a FocusControl call off the UI thread, then refreshes the overlay. */
    private void focusAsync(final Runnable r) {
        new Thread(new Runnable() {
            public void run() {
                r.run();
                ticker.post(new Runnable() {
                    public void run() { refresh(); }
                });
            }
        }, "focus-key").start();
    }

    private void toggleFocusMode() {
        if (camera == null) return;
        String current = focus.focusMode();
        // Cycle auto -> dmf -> manual (focus-mode-values on the NEX-5R: manual,auto,dmf).
        final String next = "auto".equals(current) ? "dmf" : "dmf".equals(current) ? "manual" : "auto";
        focusAsync(new Runnable() {
            public void run() { focus.setFocusMode(next); }
        });
    }

    private void autoFocus() {
        if (camera == null) return;
        focusAsync(new Runnable() {
            public void run() { focus.arm(""); }
        });
    }

    private void takePicture() {
        if (camera == null) return;
        try {
            camera.getNormalCamera().takePicture(null, null, null);
            lastResult = "picture at offset " + focus.offset();
        } catch (Throwable t) {
            lastResult = "takePicture threw " + t;
        }
        Logger.info(lastResult);
    }

    private void refresh() {
        if (bulbPage) {
            overlay.setText(bulb.status() + "\nhttp://" + ip + ":" + HttpServer.PORT + "/status");
            return;
        }
        overlay.setText("FOCUS\n"
                + "Offset: " + focus.offset() + " (window " + FocusControl.MIN_OFFSET + ".." + FocusControl.MAX_OFFSET
                + ")   Step: " + STEP_SIZES[stepIndex] + "\n"
                + "Focus mode: " + (camera == null ? "-" : focus.focusMode()) + "   Armed: " + focus.isArmed()
                + (focus.isMoving() ? "   MOVING" : "") + "\n"
                + "Calls: " + focus.calls() + "   Failed: " + focus.failures() + "\n"
                + focus.lastResult() + "\n" + lastResult + "\n\n"
                + "</> move  ^/v step  OK mode\n"
                + "half-press AF  shutter photo  SK1 bulb page  trash exit");
    }

    /**
     * Plain open. Tried 2026-11-18: Smart Remote's OpenOptions (setRecordingMode, setTargetMedia) do not
     * exist on the NEX-5R firmware (NoSuchMethodError), and on old firmware Smart Remote only sets
     * setPreview / setInheritSetting.
     */
    private static CameraEx openCamera() { return openCameraEx(); }

    /**
     * With the marker file NEX5R/OPENOPT: Smart Remote's open options on old firmware
     * (SRCtrlExecutorCreator: isImmediatelyEEStart true, isInheritSetting false), i.e. do not inherit
     * the camera's own settings. Otherwise CameraEx.open(0, null) as before.
     */
    static CameraEx openCameraEx() {
        if (!new java.io.File(android.os.Environment.getExternalStorageDirectory(), "NEX5R/OPENOPT").exists()) {
            return CameraEx.open(0, null);
        }
        CameraEx.OpenOptions o = new CameraEx.OpenOptions();
        o.setPreview(true);
        o.setInheritSetting(false);
        Logger.info("CameraEx.open with OpenOptions preview=true inheritSetting=false");
        return CameraEx.open(0, o);
    }

    /** The Version (X.Y.Z, shared with the Alpaca Server): the APK's versionName. */
    private String version() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Throwable t) {
            return "unknown";
        }
    }

    /** Turns Wi-Fi on (starting an app drops it) and starts the HTTP server; the IP shows on screen. */
    private void startNetwork() {
        try {
            wifi = (WifiManager) getSystemService(WIFI_SERVICE);
            Logger.info("Wi-Fi state " + wifi.getWifiState() + ", setWifiEnabled(true) -> " + wifi.setWifiEnabled(true));
        } catch (Throwable t) {
            Logger.error("Enabling Wi-Fi failed", t);
        }
        http = new HttpServer(new HttpServer.Api() {
            public String status() {
                return "version=" + version() + "\nip=" + ip + "\n" + bulb.state() + focus.state();
            }

            public String focus(int offset) {
                // Moving the lens during an exposure would blur it; the app also refuses to shoot
                // while a shift runs (see capture).
                if (bulb.isExposing()) return "busy: exposure running\n" + focus.state();
                return focus.moveTo(offset) + "\n" + focus.state();
            }

            public String focusArm(String mode) {
                if (bulb.isExposing()) return "busy: exposure running\n" + focus.state();
                return focus.arm(mode) + "\n" + focus.state();
            }

            public String focusMode(String mode) {
                return focus.setFocusMode(mode) + "\n" + focus.state();
            }

            public String focusState() { return focus.state(); }

            public String keys(final String mode) {
                // Fake a full shutter press (S1_1, S1_2, S2, then releases) with the scan codes a real
                // press sends. "inst": Instrumentation.sendKeySync (through the window manager, like a
                // real key); "dispatch": dispatchKeyEvent on this activity only.
                final int[] down = {ScalarInput.ISV_KEY_S1_1, ScalarInput.ISV_KEY_S1_2, ScalarInput.ISV_KEY_S2};
                final long[] pause = {500, 100, 300};
                StringBuilder out = new StringBuilder("keys " + mode + ":");
                long t0 = android.os.SystemClock.uptimeMillis();
                try {
                    for (int i = 0; i < down.length; i++) {
                        out.append(' ').append(sendKey(mode, KeyEvent.ACTION_DOWN, down[i], t0));
                        Thread.sleep(pause[i]);
                    }
                    for (int i = down.length - 1; i >= 0; i--) {
                        out.append(' ').append(sendKey(mode, KeyEvent.ACTION_UP, down[i], t0));
                        Thread.sleep(50);
                    }
                } catch (Throwable t) {
                    out.append(" threw ").append(t);
                }
                Logger.info(out.toString());
                return out.toString();
            }

            public String caution(final int mode, final String media) {
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() {
                        try {
                            if (caution == null) {
                                // SetMode refuses to run until a callback is registered (as Sony's
                                // CautionUtilityClass.registerExCallback does at boot).
                                caution = new com.sony.scalar.sysutil.didep.Caution();
                                caution.setCallback(new com.sony.scalar.sysutil.didep.Caution.CautionCallback() {
                                    public void onCallback(int[] ids) {
                                        Logger.info("Caution callback " + java.util.Arrays.toString(ids));
                                    }
                                });
                            }
                            com.sony.scalar.sysutil.didep.Caution.SetMode(mode, new String[] {media});
                            Logger.info("Caution.SetMode(" + mode + ", " + media + ") ok");
                            return "Caution.SetMode(" + mode + ", " + media + ") ok";
                        } catch (Throwable t) {
                            Logger.error("Caution.SetMode", t);
                            return "Caution.SetMode threw " + t;
                        }
                    }
                });
            }

            public String tlShoot(final String opts) {
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() {
                        if (camera != null) {
                            // Hand the camera over to TlShoot: release the UI-thread one first.
                            bulb.detach();
                            camera.release();
                            camera = null;
                            Logger.info("UI-thread camera released for tlshoot");
                        }
                        threadShot.release();
                        return tlShoot.start(opts, surfaceHolder);
                    }
                });
            }

            public String camThread(boolean on) {
                getSharedPreferences("test", MODE_PRIVATE).edit().putBoolean("camthread", on).commit();
                Logger.info("camthread -> " + on + " (next launch)");
                return "camthread=" + on + " at next launch";
            }

            public String threadShot(final int seconds, final boolean af, final boolean burst) {
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() {
                        if (camera != null) {
                            // Hand the camera over to the thread: release the UI-thread one first.
                            surfaceHolder.removeCallback(MainActivity.this);
                            bulb.detach();
                            camera.release();
                            camera = null;
                            Logger.info("UI-thread camera released for threadshot");
                        }
                        return threadShot.shoot(surfaceHolder, seconds, af, burst);
                    }
                });
            }

            public String appInfo(final String mode) {
                if (!"sony".equals(mode) && !"plain".equals(mode)) return "mode=sony|plain";
                getSharedPreferences("test", MODE_PRIVATE).edit().putString("appinfo", mode).commit();
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() { return notifyAppInfo(mode) + " (also at next launch)"; }
                });
            }

            public String inhibit(final boolean ignore) {
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() { return MainActivity.this.inhibit(ignore); }
                });
            }

            public String keyShoot(boolean on) {
                keyShoots = on;
                Logger.info("keyshoot -> " + on);
                return "keyshoot=" + on;
            }

            public String remote(final boolean on) {
                final String[] result = {"timeout"};
                final java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
                ticker.post(new Runnable() {
                    public void run() {
                        result[0] = bulb.setRemoteControlMode(on);
                        done.countDown();
                    }
                });
                try {
                    done.await(5, java.util.concurrent.TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    // return what we have
                }
                return result[0];
            }

            public String preview(final boolean on) {
                final String[] result = {"timeout"};
                final java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
                ticker.post(new Runnable() {
                    public void run() {
                        try {
                            if (on) camera.getNormalCamera().startPreview(); else camera.getNormalCamera().stopPreview();
                            result[0] = (on ? "startPreview" : "stopPreview") + " ok";
                        } catch (Throwable t) {
                            result[0] = "preview threw " + t;
                        }
                        Logger.info(result[0]);
                        done.countDown();
                    }
                });
                try {
                    done.await(5, java.util.concurrent.TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    // return what we have
                }
                return result[0];
            }

            public String shutter(final boolean slower) {
                ticker.post(new Runnable() {
                    public void run() { bulb.stepShutter(slower); }
                });
                try {
                    Thread.sleep(800);   // stepShutter logs the new speed after 300 ms
                } catch (InterruptedException e) {
                    // fall through
                }
                return bulb.state();
            }

            public String iso(final int value) {
                return onUi(new java.util.concurrent.Callable<String>() {
                    public String call() { return bulb.setIso(value); }
                });
            }

            public String capture(final int ms, final String method, final boolean af) {
                if (focus.isMoving()) return "busy: focus shift running";
                // Camera calls must run on the UI thread: post and wait for the outcome.
                final String[] result = {"timeout waiting for the UI thread"};
                final java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
                ticker.post(new Runnable() {
                    public void run() {
                        result[0] = bulb.startExposure(ms, method, af);
                        refresh();
                        done.countDown();
                    }
                });
                try {
                    done.await(5, java.util.concurrent.TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    // return what we have
                }
                return result[0];
            }
        });
        http.start();
        ticker.post(wifiWatch);
    }

    /** Sends one fake key event; returns "scan:down|up:ok" or the error. Runs off the UI thread. */
    private String sendKey(String mode, int action, int scan, long downTime) {
        final KeyEvent ev = new KeyEvent(downTime, android.os.SystemClock.uptimeMillis(), action, 0, 0, 0, 0, scan);
        String tag = scan + (action == KeyEvent.ACTION_DOWN ? ":down" : ":up");
        try {
            if ("inst".equals(mode)) {
                new android.app.Instrumentation().sendKeySync(ev);
            } else {
                final java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
                ticker.post(new Runnable() {
                    public void run() {
                        dispatchKeyEvent(ev);
                        done.countDown();
                    }
                });
                done.await(2, java.util.concurrent.TimeUnit.SECONDS);
            }
            return tag + ":ok";
        } catch (Throwable t) {
            return tag + ":" + t;
        }
    }

    /** Polls the Wi-Fi IP every 2 s and logs when it changes. */
    private final Runnable wifiWatch = new Runnable() {
        public void run() {
            String now = "-";
            try {
                int a = wifi.getConnectionInfo().getIpAddress();
                if (a != 0) now = (a & 0xff) + "." + (a >> 8 & 0xff) + "." + (a >> 16 & 0xff) + "." + (a >> 24 & 0xff);
            } catch (Throwable t) {
                now = "?";
            }
            if (!now.equals(ip)) {
                ip = now;
                Logger.info("Wi-Fi IP -> " + ip + " (state " + wifi.getWifiState() + ")");
                refresh();
            }
            // After Smart Remote (Wi-Fi Direct) or a power-off (suspend) the radio comes back enabled but
            // never rejoins the home network by itself: ask it to, every 10 s while there is no IP.
            if ("-".equals(now) && ++noIpTicks % 5 == 0) {
                try {
                    if (wifi.getWifiState() != WifiManager.WIFI_STATE_ENABLED) wifi.setWifiEnabled(true);
                    // A saved network left disabled (status 1) by another app is never rejoined by
                    // reconnect(): enable every saved network first, and log what we found.
                    StringBuilder nets = new StringBuilder();
                    java.util.List<android.net.wifi.WifiConfiguration> list = wifi.getConfiguredNetworks();
                    if (list != null) {
                        for (android.net.wifi.WifiConfiguration c : list) {
                            nets.append(' ').append(c.SSID).append(":status").append(c.status);
                            if (c.status == android.net.wifi.WifiConfiguration.Status.DISABLED) {
                                nets.append(wifi.enableNetwork(c.networkId, false) ? "->enabled" : "->enable failed");
                            }
                        }
                    }
                    Logger.info("no IP (wifi state " + wifi.getWifiState() + ", supplicant "
                            + wifi.getConnectionInfo().getSupplicantState() + "), networks" + nets
                            + ", startScan -> " + wifi.startScan() + ", reconnect -> " + wifi.reconnect());
                } catch (Throwable t) {
                    Logger.error("Wi-Fi reconnect", t);
                }
            } else if (!"-".equals(now)) {
                noIpTicks = 0;
            }
            ticker.postDelayed(this, 2000);
        }
    };

    /**
     * Starts OpenMemories: Tweak's adbd (port 5555) if it is not running, the way Tweak's "Enable ADB"
     * switch does: Tweak's libtweak.so runs its libadbd.so in the Android chroot. Saves opening Tweak
     * before each adb install. Does nothing if Tweak is not installed.
     */
    private void startAdb() {
        try {
            String lib = getPackageManager().getApplicationInfo("com.github.ma1co.openmemories.tweak", 0).nativeLibraryDir;
            String adbd = lib + "/libadbd.so";
            if (processRunning(adbd)) {
                Logger.info("adbd already running");
                return;
            }
            com.github.ma1co.openmemories.tweak.Shell.load(lib);
            com.github.ma1co.openmemories.tweak.Shell.execAndroid(adbd + " &");
            Logger.info("adbd started from " + adbd);
        } catch (Throwable t) {
            Logger.error("Starting adbd", t);
        }
    }

    /** True if a process's command line starts with cmd (as Tweak's Procfs.findProcess). */
    private static boolean processRunning(String cmd) {
        java.io.File[] procs = new java.io.File("/proc").listFiles();
        if (procs == null) return false;
        for (java.io.File p : procs) {
            try {
                Integer.parseInt(p.getName());
                java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(
                        new java.io.FileInputStream(new java.io.File(p, "cmdline"))), 256);
                String line = r.readLine();
                r.close();
                if (line != null && line.startsWith(cmd)) return true;
            } catch (Throwable t) {
                // not a pid, or gone
            }
        }
        return false;
    }

    /**
     * APO/NO disables auto power off. Required for any software shot on the NEX-5R (2026-11-18): without
     * it burstableTakePicture / takePicture wait forever (onShutter "canceled" at cancelTakePicture, no
     * file); found by bisecting TimeLapse 1.4.0's sequence, see TlShoot. APO/NORMAL restores it on exit.
     */
    void setAutoPowerOff(boolean enable) {
        android.content.Intent i = new android.content.Intent("com.android.server.DAConnectionManagerService.apo");
        i.putExtra("apo_info", enable ? "APO/NORMAL" : "APO/NO");
        sendBroadcast(i);
        Logger.info("auto power off " + (enable ? "APO/NORMAL" : "APO/NO"));
    }

    /** notifyAppInfo mode for the next launch ("plain" or "sony"), set by HTTP /appinfo. */
    private String appInfoMode() {
        return getSharedPreferences("test", MODE_PRIVATE).getString("appinfo", "plain");
    }

    private void notifyAppInfo() { notifyAppInfo(appInfoMode()); }

    /** Camera owned by ThreadShot's HandlerThread from launch (HTTP /camthread?on=1, next launch). */
    private boolean camThread() {
        // Also on when the marker file exists (created over adb before a launch).
        return getSharedPreferences("test", MODE_PRIVATE).getBoolean("camthread", false)
                || new java.io.File(android.os.Environment.getExternalStorageDirectory(), "NEX5R/CAMTHRD").exists();
    }

    /**
     * Tells the camera which app is in front. "plain": package and class only, as PMCADemo does.
     * "sony": what Sony's base app sends on entering its shooting state (AppInfo.notifyAppInfo from
     * ShootingStateEx.onResume in Smart Remote): also large_category CATEGORY_REC, small_category
     * STILL, and BaseApp's PULLING_BACK_KEYS_FOR_SHOOTING / RESUME_KEYS_FOR_SHOOTING.
     */
    private String notifyAppInfo(String mode) {
        Intent intent = new Intent("com.android.server.DAConnectionManagerService.AppInfoReceive");
        intent.putExtra("package_name", getComponentName().getPackageName());
        intent.putExtra("class_name", getComponentName().getClassName());
        if ("sony".equals(mode)) {
            intent.putExtra("large_category", "CATEGORY_REC");
            intent.putExtra("small_category", "STILL");
            intent.putExtra("pullingback_key", new String[] {"KEY_USB_CONNECT"});
            intent.putExtra("resume_key", new String[] {"KEY_POWER_SLIDE_PON", "KEY_RELEASE_APO", "KEY_PLAY_APO",
                    "KEY_MEDIA_INOUT_APO", "KEY_LENS_APO", "KEY_ACCESSORY_APO", "KEY_DEDICATED_APO",
                    "KEY_POWER_APO", "KEY_PLAY_PON"});
        }
        sendBroadcast(intent);
        Logger.info("notifyAppInfo " + mode);
        return "notifyAppInfo " + mode + " sent";
    }

    /** CameraEx.getInhibitionInfo(), after ParametersModifier.tryIgnoreInhibit() + setParameters if asked. */
    private String inhibit(boolean ignore) {
        if (camera == null) return "no camera";
        StringBuilder out = new StringBuilder();
        try {
            out.append("inhibition before ").append(camera.getInhibitionInfo());
        } catch (Throwable t) {
            out.append("getInhibitionInfo threw ").append(t);
        }
        if (ignore) {
            try {
                Camera.Parameters p = camera.getNormalCamera().getParameters();
                camera.createParametersModifier(p).tryIgnoreInhibit();
                camera.getNormalCamera().setParameters(p);
                out.append(" | tryIgnoreInhibit + setParameters ok");
            } catch (Throwable t) {
                out.append(" | tryIgnoreInhibit threw ").append(t);
            }
            try {
                out.append(" | inhibition after ").append(camera.getInhibitionInfo());
            } catch (Throwable t) {
                out.append(" | getInhibitionInfo threw ").append(t);
            }
        }
        Logger.info(out.toString());
        return out.toString();
    }

    /** Runs a camera call on the UI thread and waits up to 5 s for its result. */
    private String onUi(final java.util.concurrent.Callable<String> call) {
        final String[] result = {"timeout waiting for the UI thread"};
        final java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
        ticker.post(new Runnable() {
            public void run() {
                try {
                    result[0] = call.call();
                } catch (Throwable t) {
                    result[0] = "threw " + t;
                }
                done.countDown();
            }
        });
        try {
            done.await(5, java.util.concurrent.TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            // return what we have
        }
        return result[0];
    }
}
