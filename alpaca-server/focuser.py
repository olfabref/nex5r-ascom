"""Alpaca Focuser (IFocuserV4) responders for the lens of the Sony NEX-5R.

Absolute focuser, positions 0..32 (= camera offsets -16..16 around the last camera autofocus, see
focuserdevice.py). One responder class per member, routed by app.init_routes from the class name.
Action "arm" (Parameters: "", "auto", "dmf" or "manual": the autofocus mode, "" = config arm_mode)
re-runs the camera autofocus, then switches to the config drive_mode.
"""
from datetime import datetime, timezone
from logging import Logger

from falcon import Request

from config import Config
from exceptions import ActionNotImplementedException, InvalidOperationException, InvalidValueException
from focuserdevice import FocuserDevice
from responders import Fail, Responders, const, not_impl, to_int
from shr import StateValue, get_request_field, to_bool

logger: Logger = None

maxdev = 0                      # Single instance


class FocuserMetadata:
    Name = 'Sony NEX-5R lens'
    Version = '0.1'
    Description = 'Focus-by-wire lens on the Sony NEX-5R (camera-app shiftFocusPosition, 33 positions)'
    DeviceType = 'Focuser'
    DeviceID = 'c2a6e3f4-8d51-4b0b-9f3e-7a1d2b6c4e85'
    Info = 'nex5r-ascom Alpaca server\nImplements IFocuserV4'
    MaxDeviceNumber = maxdev
    InterfaceVersion = 4        # IFocuserV4 (Platform 7)


dev: FocuserDevice = None


def start_focuser_device(lgr: Logger):
    global dev, logger
    logger = lgr
    dev = FocuserDevice(lgr, Config.camera_url, Config.focus_arm_mode, Config.focus_drive_mode,
                        Config.focus_arm_on_connect)


_r = Responders('Focuser', __name__, lambda: dev.connected, maxdev)
_property = _r.property
_method = _r.method


def _set_connected(value: str):
    if to_bool(value):
        dev.connect()
    else:
        dev.disconnect()


def _move(req: Request):
    pos = to_int(get_request_field('Position', req))
    if not 0 <= pos <= dev.max_step:
        raise Fail(InvalidValueException(f'Position {pos} out of 0..{dev.max_step}'))
    try:
        dev.move(pos)
    except RuntimeError as e:
        raise Fail(InvalidOperationException(str(e)))


def _set_temp_comp(value: str):
    if to_bool(value):
        raise Fail(InvalidValueException('no temperature compensation'))


def _action(req: Request):
    name = get_request_field('Action', req).strip().lower()
    params = get_request_field('Parameters', req, default='').strip().lower()
    if name != 'arm':
        raise Fail(ActionNotImplementedException(f'unknown action {name!r}'))
    if params not in ('', 'auto', 'dmf', 'manual'):
        raise Fail(InvalidValueException('Parameters: "", "auto", "dmf" or "manual"'))
    _r.need_connection()
    try:
        dev.arm(params or None)         # "" = arm_mode from config
    except RuntimeError as e:
        raise Fail(InvalidOperationException(str(e)))
    return f'armed: position {dev.position}'


def _device_state():
    return [StateValue('IsMoving', dev.is_moving),
            StateValue('Position', dev.position),
            StateValue('TimeStamp', datetime.now(timezone.utc).isoformat())]


_MEMBERS = [
    _property('Description', const(FocuserMetadata.Description), connected=False),
    _property('DriverInfo', const(FocuserMetadata.Info), connected=False),
    _property('DriverVersion', const(FocuserMetadata.Version), connected=False),
    _property('InterfaceVersion', const(FocuserMetadata.InterfaceVersion), connected=False),
    _property('Name', const(FocuserMetadata.Name), connected=False),
    _property('SupportedActions', const(['arm']), connected=False),
    _property('Connected', lambda: dev.connected, _set_connected, connected=False),
    _property('Connecting', const(False), connected=False),
    _method('Connect', lambda req: dev.connect(), connected=False),
    _method('Disconnect', lambda req: dev.disconnect(), connected=False),
    _property('DeviceState', _device_state),
    _method('Action', _action, connected=False),
    _method('CommandBlind', not_impl, connected=False),
    _method('CommandBool', not_impl, connected=False),
    _method('CommandString', not_impl, connected=False),
    # focuser
    _property('Absolute', const(True)),
    _property('MaxStep', lambda: dev.max_step),
    _property('MaxIncrement', lambda: dev.max_step),
    _property('Position', lambda: dev.position),
    _property('IsMoving', lambda: dev.is_moving),
    _property('StepSize', not_impl),                  # not measured
    _property('TempCompAvailable', const(False)),
    _property('TempComp', const(False), _set_temp_comp),
    _property('Temperature', not_impl),
    _method('Halt', not_impl),                        # a shift (~300 ms) cannot be interrupted
    _method('Move', _move),
]

# app.init_routes routes every class defined in this module by its lower-case name.
for _cls in _MEMBERS:
    globals()[_cls.__name__] = _cls
del _cls
