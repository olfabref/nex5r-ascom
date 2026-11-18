package com.github.olfabref.nex5r;

import android.os.Environment;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.util.Arrays;
import java.util.Comparator;

/**
 * Minimal HTTP/1.0 server for the feasibility test: can the Mac drive a capture and fetch the ARW over Wi-Fi?
 *
 *   GET /status             camera state (text)
 *   GET /capture?seconds=N[&method=normal|burstable|direct|dnormal|dburst|afnormal|afburst][&af=1]
 *                           timed Bulb exposure (the shutter must already be on BULB), see BulbTest
 *   GET /shutter?dir=slower|faster  one shutter speed step
 *   GET /preview?on=0|1     stopPreview / startPreview
 *   GET /remote?on=0|1      ParametersModifier.setRemoteControlMode
 *   GET /keyshoot?on=0|1    0: a physical full press does not call takePicture (firmware test)
 *   GET /keys?mode=inst|dispatch  fake full shutter press (S1_1, S1_2, S2) sent to this app
 *   GET /appinfo?mode=sony|plain  resend the DAConnectionManagerService app info now (sony: with
 *                           CATEGORY_REC / STILL and the key lists, as Sony's shooting state does);
 *                           also remembered for the next launch
 *   GET /inhibit[?ignore=1] CameraEx.getInhibitionInfo(); ignore=1 first applies
 *                           ParametersModifier.tryIgnoreInhibit() + setParameters
 *   GET /threadshot?seconds=N[&af=0][&burst=0]  shot with the camera reopened on a HandlerThread
 *                           (Sony's way), see ThreadShot; relaunch the app afterwards
 *   GET /logcat[?bg=1|stop=1]  logcat ring buffer; bg=1 starts a detached logcat to SRLOG.TXT;
 *                           stop=1 kills it (the FAT driver locks an open file)
 *   GET /srlog              /mnt/sdcard/SRLOG.TXT
 *   GET /files              DCIM files, newest first: "100MSDCF/DSC04081.ARW 16318464"
 *   GET /dcim/<dir>/<file>  one file from DCIM
 *   GET /log                NEX5R/LOG.TXT
 *
 * One thread per connection; camera calls go through {@link Api}, which runs them on the UI thread.
 */
final class HttpServer {
    static final int PORT = 8080;

    interface Api {
        String status();

        String capture(int seconds, String method, boolean af);

        String shutter(boolean slower);

        String preview(boolean on);

        String remote(boolean on);

        String keyShoot(boolean on);

        String keys(String mode);

        String appInfo(String mode);

        String inhibit(boolean ignore);

        String threadShot(int seconds, boolean af, boolean burst);

        String camThread(boolean on);

        String caution(int mode, String media);
    }

    private final Api api;
    private ServerSocket socket;

    HttpServer(Api api) { this.api = api; }

    void start() {
        new Thread(new Runnable() {
            public void run() { serve(); }
        }, "http-accept").start();
    }

    void stop() {
        try {
            if (socket != null) socket.close();
        } catch (IOException e) {
            // closing anyway
        }
    }

    private void serve() {
        try {
            socket = new ServerSocket(PORT);
            Logger.info("HTTP server listening on port " + PORT);
            while (true) {
                final Socket client = socket.accept();
                new Thread(new Runnable() {
                    public void run() { handle(client); }
                }, "http-client").start();
            }
        } catch (IOException e) {
            Logger.info("HTTP server stopped: " + e);
        }
    }

    private void handle(Socket client) {
        long start = System.currentTimeMillis();
        String target = "?";
        try {
            client.setSoTimeout(30000);
            BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream()), 1024);
            String line = in.readLine();
            if (line == null) return;
            String[] parts = line.split(" ");
            target = parts.length > 1 ? parts[1] : "/";
            while ((line = in.readLine()) != null && line.length() > 0) {
                // headers ignored
            }
            OutputStream out = client.getOutputStream();
            String path = target, query = "";
            int q = target.indexOf('?');
            if (q >= 0) {
                path = target.substring(0, q);
                query = target.substring(q + 1);
            }
            long bytes = route(URLDecoder.decode(path), query, out);
            out.flush();
            long ms = System.currentTimeMillis() - start;
            Logger.info("HTTP " + target + " -> " + bytes + " B in " + ms + " ms"
                    + (ms > 0 && bytes > 100000 ? " (" + (bytes / ms) + " kB/s)" : ""));
        } catch (Throwable t) {
            Logger.info("HTTP " + target + " failed: " + t);
        } finally {
            try {
                client.close();
            } catch (IOException e) {
                // nothing to do
            }
        }
    }

    private long route(String path, String query, OutputStream out) throws IOException {
        if (path.equals("/status")) return text(out, 200, api.status());
        if (path.equals("/capture")) {
            int seconds;
            try {
                seconds = Integer.parseInt(param(query, "seconds"));
            } catch (NumberFormatException e) {
                return text(out, 400, "seconds=N required\n");
            }
            if (seconds < 1 || seconds > 3600) return text(out, 400, "seconds out of 1..3600\n");
            String method = param(query, "method");
            return text(out, 200, api.capture(seconds, method.length() == 0 ? "normal" : method,
                    "1".equals(param(query, "af"))) + "\n");
        }
        if (path.equals("/shutter")) {
            String dir = param(query, "dir");
            if (!dir.equals("slower") && !dir.equals("faster")) return text(out, 400, "dir=slower|faster required\n");
            return text(out, 200, api.shutter(dir.equals("slower")) + "\n");
        }
        if (path.equals("/preview")) return text(out, 200, api.preview("1".equals(param(query, "on"))) + "\n");
        if (path.equals("/remote")) return text(out, 200, api.remote("1".equals(param(query, "on"))) + "\n");
        if (path.equals("/keyshoot")) return text(out, 200, api.keyShoot("1".equals(param(query, "on"))) + "\n");
        if (path.equals("/appinfo")) {
            String mode = param(query, "mode");
            return text(out, 200, api.appInfo(mode.length() == 0 ? "sony" : mode) + "\n");
        }
        if (path.equals("/caution")) {
            // Smart Remote: Caution.SetMode(MODE_ID_STILL_REC = 3, {"1000"}) on entering shooting and
            // before each shot (CautionUtilityClass). Our app never sets it (default 16 = SCALARA_DEFAULT?).
            String m = param(query, "mode");
            String media = param(query, "media");
            int mode;
            try {
                mode = m.length() == 0 ? 3 : Integer.parseInt(m);
            } catch (NumberFormatException e) {
                return text(out, 400, "mode=N\n");
            }
            return text(out, 200, api.caution(mode, media.length() == 0 ? "1000" : media) + "\n");
        }
        if (path.equals("/camthread")) return text(out, 200, api.camThread("1".equals(param(query, "on"))) + "\n");
        if (path.equals("/threadshot")) {
            int seconds;
            try {
                seconds = Integer.parseInt(param(query, "seconds"));
            } catch (NumberFormatException e) {
                seconds = 8;
            }
            return text(out, 200, api.threadShot(seconds, !"0".equals(param(query, "af")),
                    !"0".equals(param(query, "burst"))) + "\n");
        }
        if (path.equals("/srlog")) return file(out, new File("/mnt/sdcard/SRLOG.TXT"), "text/plain");
        if (path.equals("/logcat")) {
            if ("1".equals(param(query, "stop"))) return text(out, 200, stopLogcats());
            return text(out, 200, logcat("1".equals(param(query, "bg"))));
        }
        if (path.equals("/inhibit")) return text(out, 200, api.inhibit("1".equals(param(query, "ignore"))) + "\n");
        if (path.equals("/keys")) {
            String mode = param(query, "mode");
            return text(out, 200, api.keys(mode.length() == 0 ? "inst" : mode) + "\n");
        }
        if (path.equals("/files")) return text(out, 200, listDcim());
        if (path.equals("/log")) return file(out, Logger.getFile(), "text/plain");
        if (path.startsWith("/dcim/")) {
            String rel = path.substring("/dcim/".length());
            if (rel.contains("..")) return text(out, 400, "bad path\n");
            return file(out, new File(dcim(), rel), "application/octet-stream");
        }
        return text(out, 404, "not found\n");
    }

    private static File dcim() { return new File(Environment.getExternalStorageDirectory(), "DCIM"); }

    private static String listDcim() {
        File[] dirs = dcim().listFiles();
        if (dirs == null) return "";
        java.util.List<File> all = new java.util.ArrayList<File>();
        for (File dir : dirs) {
            File[] files = dir.listFiles();
            if (files != null) all.addAll(Arrays.asList(files));
        }
        // Newest first by name: DSCnnnnn numbers grow, and the camera clock (1970) makes dates useless.
        File[] sorted = all.toArray(new File[0]);
        Arrays.sort(sorted, new Comparator<File>() {
            public int compare(File a, File b) { return b.getName().compareTo(a.getName()); }
        });
        StringBuilder out = new StringBuilder();
        for (File f : sorted) {
            out.append(f.getParentFile().getName()).append('/').append(f.getName())
                    .append(' ').append(f.length()).append('\n');
        }
        return out.toString();
    }

    /** Log tags that flood the 64 KB ring buffer during live view (one line per preview frame). */
    private static final String[] QUIET = {"CameraSeqHAL:S", "DevMemoryHAL:S", "MediaPlayerService:S"};

    /**
     * bg=false: the logcat ring buffer now (logcat -d). bg=true: starts a logcat writing to
     * /mnt/sdcard/srlog.txt (rotated, 8 x 2 MB) that should outlive this app (Android 2.3 kills only the
     * app's own pid), to record another app such as Smart Remote. Needs READ_LOGS.
     */
    private static String logcat(boolean bg) {
        java.util.List<String> cmd = new java.util.ArrayList<String>(Arrays.asList("logcat", "-v", "time"));
        if (bg) {
            cmd.addAll(Arrays.asList("-f", "/mnt/sdcard/srlog.txt", "-r", "2048", "-n", "8"));
        } else {
            cmd.add("-d");
        }
        cmd.addAll(Arrays.asList(QUIET));
        try {
            Process p = new ProcessBuilder(cmd).redirectErrorStream(true).start();
            if (bg) return "background logcat started: /mnt/sdcard/srlog.txt\n";
            StringBuilder out = new StringBuilder();
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()), 8192);
            for (String line; (line = r.readLine()) != null; ) out.append(line).append('\n');
            return out.toString();
        } catch (IOException e) {
            return "logcat failed: " + e + "\n";
        }
    }

    /**
     * Kills the background logcats this app started (same uid). Needed to read SRLOG.TXT: the camera's
     * FAT driver refuses to open a file another process holds ("Device or resource busy"), and powering
     * the NEX-5R off only suspends it.
     */
    private static String stopLogcats() {
        StringBuilder out = new StringBuilder("killed:");
        File[] procs = new File("/proc").listFiles();
        if (procs != null) {
            for (File p : procs) {
                int pid;
                try {
                    pid = Integer.parseInt(p.getName());
                } catch (NumberFormatException e) {
                    continue;
                }
                try {
                    BufferedReader r = new BufferedReader(new InputStreamReader(
                            new FileInputStream(new File(p, "cmdline"))), 256);
                    String cmd = r.readLine();
                    r.close();
                    if (cmd != null && cmd.startsWith("logcat") && cmd.contains("srlog")) {
                        android.os.Process.killProcess(pid);
                        out.append(' ').append(pid);
                    }
                } catch (IOException e) {
                    // not ours or gone
                }
            }
        }
        return out.append('\n').toString();
    }

    private static String param(String query, String name) {
        for (String kv : query.split("&")) {
            if (kv.startsWith(name + "=")) return kv.substring(name.length() + 1);
        }
        return "";
    }

    private static long text(OutputStream out, int code, String body) throws IOException {
        byte[] bytes = body.getBytes("UTF-8");
        header(out, code, "text/plain; charset=utf-8", bytes.length);
        out.write(bytes);
        return bytes.length;
    }

    private static long file(OutputStream out, File f, String type) throws IOException {
        if (!f.isFile()) return text(out, 404, "no such file\n");
        long length = f.length();
        header(out, 200, type, length);
        InputStream in = new FileInputStream(f);
        try {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        } finally {
            in.close();
        }
        return length;
    }

    private static void header(OutputStream out, int code, String type, long length) throws IOException {
        String reason = code == 200 ? "OK" : code == 400 ? "Bad Request" : "Not Found";
        out.write(("HTTP/1.0 " + code + " " + reason + "\r\nContent-Type: " + type + "\r\nContent-Length: " + length
                + "\r\nConnection: close\r\n\r\n").getBytes("US-ASCII"));
    }
}
