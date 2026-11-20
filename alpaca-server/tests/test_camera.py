"""Camera device through the Alpaca API, as N.I.N.A. drives it, against the fake camera-app."""
import struct
import time

import numpy as np

CAMERA_STATE_ERROR = 5


def wait_image_ready(alpaca, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert alpaca.get('camera', 'camerastate') != CAMERA_STATE_ERROR
        if alpaca.get('camera', 'imageready'):
            return
        time.sleep(0.25)
    raise AssertionError('ImageReady never came')


def test_one_exposure_gives_the_sample_image_as_imagebytes(alpaca):
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.get('camera', 'connected') is True
    assert alpaca.get('camera', 'gainmin') == 100            # ISO Auto (0) is left out

    body = alpaca.put('camera', 'startexposure', Duration=1.0, Light='true')
    assert body['ErrorNumber'] == 0, body['ErrorMessage']
    wait_image_ready(alpaca)

    ctype, raw = alpaca.request('GET', '/api/v1/camera/0/imagearray',
                                headers={'Accept': 'application/imagebytes'})
    assert ctype == 'application/imagebytes'
    (version, error, _, _, data_start, image_type, transmission_type,
     rank, dim1, dim2, dim3) = struct.unpack('<11i', raw[:44])
    assert (version, error, data_start, image_type, transmission_type, rank) == (1, 0, 44, 2, 8, 2)
    assert (dim1, dim2, dim3) == (64, 40, 0)                 # X = width, Y = height of sample.ARW
    img = np.frombuffer(raw[44:], dtype='<u2').reshape(dim1, dim2)
    # sample.ARW pixel (x, y) = 512 + 4 x + 256 y
    assert img[0, 0] == 512 and img[1, 0] == 516 and img[0, 1] == 768 and img[63, 39] == 512 + 252 + 9984

    # GRBG in sample.ARW: red at (1, 0), not the config default (0, 0)
    assert alpaca.get('camera', 'bayeroffsetx') == 1
    assert alpaca.get('camera', 'bayeroffsety') == 0
    assert alpaca.get('camera', 'lastexposureduration') == 1.0
