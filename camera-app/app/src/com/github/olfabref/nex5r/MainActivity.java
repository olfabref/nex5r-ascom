package com.github.olfabref.nex5r;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.KeyEvent;
import android.widget.TextView;

import com.github.ma1co.openmemories.framework.DeviceInfo;
import com.sony.scalar.hardware.CameraEx;
import com.sony.scalar.sysutil.ScalarInput;

/**
 * Toolchain smoke test: shows device info and which focus APIs exist on this camera.
 * The trash button exits.
 */
public class MainActivity extends Activity {
    private TextView text;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        text = new TextView(this);
        text.setTextSize(18);
        setContentView(text);
    }

    @Override
    protected void onResume() {
        super.onResume();
        notifyAppInfo();

        StringBuilder report = new StringBuilder("NEX5R Dev OK\n\n");
        try {
            DeviceInfo info = DeviceInfo.getInstance();
            report.append("Model: ").append(info.getModel()).append('\n');
            report.append("Firmware: ").append(info.getFirmwareVersion()).append('\n');
            report.append("API version: ").append(info.getApiVersion()).append('\n');
            report.append("Android: ").append(info.getAndroidVersion()).append('\n');
        } catch (Throwable t) {
            report.append("DeviceInfo failed: ").append(t).append('\n');
        }
        report.append("\nshiftFocusPosition: ").append(hasMethod("shiftFocusPosition", int.class));
        report.append("\nstartOneShotFocusDrive: ").append(hasMethod("startOneShotFocusDrive", int.class, int.class));
        report.append("\n\nTrash = exit");

        text.setText(report);
        Logger.info(report.toString().replace("\n", " | "));
    }

    private static boolean hasMethod(String name, Class<?>... params) {
        try {
            CameraEx.class.getMethod(name, params);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        int scan = event.getScanCode();
        if (scan == ScalarInput.ISV_KEY_DELETE || scan == ScalarInput.ISV_KEY_SK2) {
            finish();
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    /** Tells the camera which app is in front, as PMCADemo does; without it key handling can misbehave. */
    private void notifyAppInfo() {
        Intent intent = new Intent("com.android.server.DAConnectionManagerService.AppInfoReceive");
        intent.putExtra("package_name", getComponentName().getPackageName());
        intent.putExtra("class_name", getComponentName().getClassName());
        sendBroadcast(intent);
    }
}
