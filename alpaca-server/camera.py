"""Alpaca Camera (ICameraV4) responders for the Sony NEX-5R.

Same structure as AlpycaDevice's rotator.py (one Falcon responder class per member, routed by
app.init_routes from the class name), but the classes are generated from a table: the Camera
interface has ~70 members and most are constants for this camera.

Image transfer: ImageBytes (application/imagebytes) when the client accepts it, as N.I.N.A. does;
JSON otherwise (slow for 16 MP).
"""
import json
import struct
from datetime import datetime, timezone
from logging import Logger

import numpy as np
from falcon import Request, Response

from cameradevice import CameraDevice, CameraState
from config import Config
from exceptions import InvalidOperationException, InvalidValueException, ValueNotSetException
from responders import Fail, Responders, const, not_impl, to_int
from shr import PropertyResponse, StateValue, get_request_field, getNextTransId, to_bool

logger: Logger = None

maxdev = 0                      # Single instance


class CameraMetadata:
    Name = 'Sony NEX-5R'
    Version = '0.1'
    Description = 'Sony NEX-5R over Wi-Fi (camera-app on the camera, timed Bulb, ARW Bayer data)'
    DeviceType = 'Camera'
    DeviceID = '6b1f3c1e-2a7d-4f4e-9a55-5d1c0e7b9a42'
    Info = 'nex5r-ascom Alpaca server\nImplements ICameraV4'
    MaxDeviceNumber = maxdev
    InterfaceVersion = 4        # ICameraV4 (Platform 7)


dev: CameraDevice = None


class _Sub:
    """Requested subframe and binning (binning is always 1)."""
    start_x = 0
    start_y = 0
    num_x = 0
    num_y = 0


def start_camera_device(lgr: Logger):
    global dev, logger
    logger = lgr
    dev = CameraDevice(lgr, Config.camera_url, Config.file_timeout)
    _Sub.num_x = Config.sensor_x
    _Sub.num_y = Config.sensor_y


_r = Responders('Camera', __name__, lambda: dev.connected, maxdev)
_property = _r.property
_method = _r.method
_const = const
_int = to_int
_not_impl = not_impl
_need_connection = _r.need_connection
_wrap = _r.wrap


# --- members ------------------------------------------------------------------------------------

def _set_connected(value: str):
    if to_bool(value):
        dev.connect()
    else:
        dev.disconnect()


def _set_bin(value: str):
    if _int(value) != 1:
        raise Fail(InvalidValueException('binning is not supported (1 only)'))


def _setter(attr: str):
    def set_(value: str):
        v = _int(value)
        if v < 0:
            raise Fail(InvalidValueException(f'{attr} must be >= 0'))
        setattr(_Sub, attr, v)
    return set_


def _isos() -> list[int]:
    if not dev.isos:
        raise Fail(InvalidOperationException('the camera reported no ISO values'))
    return dev.isos


def _gain():
    return _isos()[dev.gain_index]


def _set_gain(value: str):
    """Gain value mode: the ISO itself, snapped to the nearest supported ISO (in stops)."""
    v = _int(value)
    isos = _isos()
    if not isos[0] <= v <= isos[-1]:
        raise Fail(InvalidValueException(f'Gain {v} out of {isos[0]}..{isos[-1]} (ISO)'))
    dev.gain_index = min(range(len(isos)), key=lambda i: abs(np.log2(isos[i] / v)))
    if isos[dev.gain_index] != v:
        logger.info(f'[camera] Gain {v} -> ISO {isos[dev.gain_index]}')


def _set_readout_mode(value: str):
    if _int(value) != 0:
        raise Fail(InvalidValueException('only readout mode 0 (ARW)'))


def _bayer(axis: int):
    def get():
        if Config.sensor_mono:
            _not_impl()
        if dev.bayer_offset is not None:
            return dev.bayer_offset[axis]
        return (Config.bayer_offset_x, Config.bayer_offset_y)[axis]
    return get


def _last_duration():
    if dev.last_duration is None:
        raise Fail(ValueNotSetException('no exposure yet'))
    return dev.last_duration


def _last_start():
    if dev.last_start is None:
        raise Fail(ValueNotSetException('no exposure yet'))
    return dev.last_start


def _start_exposure(req: Request):
    try:
        duration = float(get_request_field('Duration', req))
    except ValueError:
        raise Fail(InvalidValueException('Duration is not a number'))
    to_bool(get_request_field('Light', req))     # validated; dark frames need the lens cap
    if not Config.exposure_min <= duration <= Config.exposure_max:
        raise Fail(InvalidValueException(
            f'Duration {duration} out of {Config.exposure_min}..{Config.exposure_max} s'))
    if _Sub.num_x < 1 or _Sub.num_y < 1 or _Sub.start_x + _Sub.num_x > Config.sensor_x \
            or _Sub.start_y + _Sub.num_y > Config.sensor_y:
        raise Fail(InvalidValueException(
            f'subframe {_Sub.start_x},{_Sub.start_y} {_Sub.num_x}x{_Sub.num_y} outside the sensor'))
    try:
        dev.start_exposure(duration)
    except RuntimeError as e:
        raise Fail(InvalidOperationException(str(e)))


def _device_state():
    return [StateValue('CameraState', int(dev.state)),
            StateValue('ImageReady', dev.image_ready),
            StateValue('PercentCompleted', dev.percent_completed()),
            StateValue('TimeStamp', datetime.now(timezone.utc).isoformat())]


def _not_impl_method(req):
    _not_impl()


_DRIVER = [
    _property('Description', _const(CameraMetadata.Description), connected=False),
    _property('DriverInfo', _const(CameraMetadata.Info), connected=False),
    _property('DriverVersion', _const(CameraMetadata.Version), connected=False),
    _property('InterfaceVersion', _const(CameraMetadata.InterfaceVersion), connected=False),
    _property('Name', _const(CameraMetadata.Name), connected=False),
    _property('SupportedActions', _const([]), connected=False),
    _property('Connected', lambda: dev.connected, _set_connected, connected=False),
    _property('Connecting', _const(False), connected=False),
    _method('Connect', lambda req: dev.connect(), connected=False),
    _method('Disconnect', lambda req: dev.disconnect(), connected=False),
    _property('DeviceState', _device_state),
    _method('Action', _not_impl_method, connected=False),
    _method('CommandBlind', _not_impl_method, connected=False),
    _method('CommandBool', _not_impl_method, connected=False),
    _method('CommandString', _not_impl_method, connected=False),
]

# Config values are read at call time: app.main may load another configuration after this import.
_CAMERA = [
    # geometry
    _property('CameraXSize', lambda: Config.sensor_x),
    _property('CameraYSize', lambda: Config.sensor_y),
    _property('PixelSizeX', lambda: Config.pixel_size_um),
    _property('PixelSizeY', lambda: Config.pixel_size_um),
    _property('SensorName', _const('Sony NEX-5R APS-C')),
    # RGGB; 'mono' sends the same Bayer data as monochrome (no debayering in the client)
    _property('SensorType', lambda: 0 if Config.sensor_mono else 2),
    _property('BayerOffsetX', _bayer(0)),
    _property('BayerOffsetY', _bayer(1)),
    _property('BinX', _const(1), _set_bin),
    _property('BinY', _const(1), _set_bin),
    _property('MaxBinX', _const(1)),
    _property('MaxBinY', _const(1)),
    _property('CanAsymmetricBin', _const(False)),
    _property('StartX', lambda: _Sub.start_x, _setter('start_x')),
    _property('StartY', lambda: _Sub.start_y, _setter('start_y')),
    _property('NumX', lambda: _Sub.num_x, _setter('num_x')),
    _property('NumY', lambda: _Sub.num_y, _setter('num_y')),
    # pixel values
    _property('MaxADU', lambda: Config.max_adu),
    _property('ElectronsPerADU', _const(1.0)),           # not measured
    _property('FullWellCapacity', lambda: float(Config.max_adu)),
    _property('ReadoutMode', _const(0), _set_readout_mode),
    _property('ReadoutModes', _const(['ARW (Bayer RAW)'])),
    _property('CanFastReadout', _const(False)),
    _property('FastReadout', _not_impl, lambda v: _not_impl()),
    # gain = ISO, in value mode (GainMin/GainMax). List mode (Gains) would make N.I.N.A. show
    # indices 0..n instead of ISO values: it maps gain names to their index.
    _property('Gains', _not_impl),
    _property('Gain', _gain, _set_gain),
    _property('GainMin', lambda: _isos()[0]),
    _property('GainMax', lambda: _isos()[-1]),
    _property('Offset', _not_impl, lambda v: _not_impl()),
    _property('Offsets', _not_impl),
    _property('OffsetMin', _not_impl),
    _property('OffsetMax', _not_impl),
    # exposure
    _property('ExposureMin', lambda: Config.exposure_min),
    _property('ExposureMax', lambda: Config.exposure_max),
    _property('ExposureResolution', _const(0.001)),
    _property('HasShutter', _const(False)),
    _property('CanAbortExposure', _const(False)),
    _property('CanStopExposure', _const(False)),
    _method('AbortExposure', _not_impl_method),
    _method('StopExposure', _not_impl_method),
    _method('StartExposure', _start_exposure),
    _property('CameraState', lambda: int(dev.state)),
    _property('ImageReady', lambda: dev.image_ready),
    _property('PercentCompleted', lambda: dev.percent_completed()),
    _property('LastExposureDuration', _last_duration),
    _property('LastExposureStartTime', _last_start),
    _property('SubExposureDuration', _not_impl, lambda v: _not_impl()),
    # cooling and guiding: none
    _property('CanGetCoolerPower', _const(False)),
    _property('CanSetCCDTemperature', _const(False)),
    _property('CanPulseGuide', _const(False)),
    _property('CCDTemperature', _not_impl),
    _property('HeatSinkTemperature', _not_impl),
    _property('CoolerOn', _not_impl, lambda v: _not_impl()),
    _property('CoolerPower', _not_impl),
    _property('SetCCDTemperature', _not_impl, lambda v: _not_impl()),
    _property('IsPulseGuiding', _not_impl),
    _method('PulseGuide', _not_impl_method),
]

# app.init_routes routes every class defined in this module by its lower-case name.
for _cls in _DRIVER + _CAMERA:
    globals()[_cls.__name__] = _cls
del _cls


# --- ImageArray ---------------------------------------------------------------------------------

def _subframe() -> np.ndarray:
    if dev.state == CameraState.ERROR:
        raise Fail(InvalidOperationException(f'exposure failed: {dev.error}'))
    if not dev.image_ready:
        raise Fail(InvalidOperationException('no image ready'))
    img = dev.image                                   # (X, Y)
    return img[_Sub.start_x:_Sub.start_x + _Sub.num_x, _Sub.start_y:_Sub.start_y + _Sub.num_y]


def _image_bytes(req: Request, img: np.ndarray) -> bytes:
    """Alpaca ImageBytes: 44-byte header, then UInt16 pixels with Y varying fastest ([X][Y] order)."""
    client_tid = int(get_request_field('ClientTransactionID', req, False, 0))
    header = struct.pack('<11i', 1, 0, client_tid, getNextTransId(), 44,
                         2,              # ImageElementType Int32
                         8,              # TransmissionElementType UInt16
                         2, img.shape[0], img.shape[1], 0)
    return header + np.ascontiguousarray(img, dtype='<u2').tobytes()


def _image_responder(name: str):
    def on_get(self, req: Request, resp: Response, devnum: int):
        try:
            _need_connection()
            img = _subframe()
            if 'application/imagebytes' in (req.get_header('Accept') or ''):
                resp.content_type = 'application/imagebytes'
                resp.data = _image_bytes(req, img)
                logger.info(f'{req.remote_addr} <- ImageBytes {img.shape[0]}x{img.shape[1]}')
                return
            body = PropertyResponse(None, req)
            body.Type = 2
            body.Rank = 2
            body.Value = img.tolist()
            resp.text = json.dumps(body.__dict__)
        except Exception as ex:
            resp.text = PropertyResponse(None, req, _wrap(ex, name)).json
    return _r.responder(name, {'on_get': on_get})


imagearray = _image_responder('ImageArray')
imagearrayvariant = _image_responder('ImageArrayVariant')
