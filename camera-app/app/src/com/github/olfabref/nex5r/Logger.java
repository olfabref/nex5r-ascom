package com.github.olfabref.nex5r;

import android.os.Environment;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;

/** Appends to NEX5R/LOG.TXT on the SD card: the camera wipes logcat whenever an app starts or exits. */
public final class Logger {
    private Logger() {}

    public static File getFile() {
        return new File(Environment.getExternalStorageDirectory(), "NEX5R/LOG.TXT");
    }

    public static void info(String msg) { log("INFO", msg); }

    public static void error(String msg, Throwable t) { log("ERROR", msg + ": " + stackTrace(t)); }

    /** Logs uncaught exceptions with their stack trace before the app dies (logcat is wiped on restart). */
    public static void installCrashHandler() {
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        if (previous instanceof CrashHandler) return;
        Thread.setDefaultUncaughtExceptionHandler(new CrashHandler(previous));
    }

    private static final class CrashHandler implements Thread.UncaughtExceptionHandler {
        private final Thread.UncaughtExceptionHandler previous;

        CrashHandler(Thread.UncaughtExceptionHandler previous) { this.previous = previous; }

        public void uncaughtException(Thread thread, Throwable t) {
            log("CRASH", "thread " + thread.getName() + ": " + stackTrace(t));
            if (previous != null) previous.uncaughtException(thread, t);
        }
    }

    private static String stackTrace(Throwable t) {
        java.io.StringWriter out = new java.io.StringWriter();
        t.printStackTrace(new java.io.PrintWriter(out));
        return out.toString();
    }

    private static synchronized void log(String level, String msg) {
        try {
            File file = getFile();
            file.getParentFile().mkdirs();
            BufferedWriter writer = new BufferedWriter(new FileWriter(file, true));
            try {
                String time = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(new Date());
                writer.append(time).append(" [").append(level).append("] ").append(msg);
                writer.newLine();
            } finally {
                writer.close();
            }
        } catch (IOException e) {
            // Nowhere left to report it.
        }
    }
}
