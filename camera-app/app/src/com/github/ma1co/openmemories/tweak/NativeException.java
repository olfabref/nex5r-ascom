package com.github.ma1co.openmemories.tweak;

/** Thrown by Tweak's libtweak.so (looked up by this exact name). Copied from OpenMemories: Tweak. */
public class NativeException extends Exception {
    public NativeException(String message) {
        super(message);
    }
}
