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

    public static void error(String msg, Throwable t) { log("ERROR", msg + ": " + t); }

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
