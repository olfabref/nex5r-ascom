"""Focuser device through the Alpaca API, against the fake camera-app."""
import time


def test_connect_arms_then_move_to_a_position_and_read_it_back(alpaca, camera_app):
    assert not camera_app.camera.focus_armed
    assert alpaca.put('focuser', 'connected', Connected='true')['ErrorNumber'] == 0

    # Arming at Connect: autofocus in manual, then focus mode auto; position 16 = the Arming point
    assert camera_app.camera.focus_armed
    assert camera_app.camera.focus_mode == 'auto'
    assert alpaca.get('focuser', 'position') == 16
    assert alpaca.get('focuser', 'maxstep') == 32

    body = alpaca.put('focuser', 'move', Position=20)
    assert body['ErrorNumber'] == 0, body['ErrorMessage']
    deadline = time.monotonic() + 5
    while alpaca.get('focuser', 'ismoving'):
        assert time.monotonic() < deadline, 'still moving'
        time.sleep(0.05)
    assert alpaca.get('focuser', 'position') == 20
    assert camera_app.camera.focus_offset == 4
