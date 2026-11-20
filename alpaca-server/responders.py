"""Falcon responder factories shared by the Alpaca devices (camera.py, focuser.py).

Each Alpaca member is one responder class named after it (app.init_routes routes a module's classes by
their lower-case name). The factories build those classes from a getter / setter / method, check the
connection, and turn exceptions into Alpaca errors.
"""
from falcon import Request, Response, before

from exceptions import DriverException, InvalidValueException, NotConnectedException, NotImplementedException
from shr import MethodResponse, PreProcessRequest, PropertyResponse, get_request_field


class Fail(Exception):
    """Carries an Alpaca error object (exceptions.py) out of a getter/setter/method."""
    def __init__(self, err):
        super().__init__(getattr(err, 'Message', str(err)))
        self.err = err


def not_impl(*_args):
    raise Fail(NotImplementedException())


def const(value):
    return lambda: value


def to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        raise Fail(InvalidValueException(f'not an integer: {s!r}'))


class Responders:
    """Factories for one device type: kind ('Camera'), the module the classes belong to (its
    __name__, for app.init_routes), and how to tell whether the device is connected."""

    def __init__(self, kind: str, module: str, is_connected, maxdev: int = 0):
        self.kind = kind
        self.module = module
        self.is_connected = is_connected
        self.maxdev = maxdev

    def need_connection(self):
        if not self.is_connected():
            raise Fail(NotConnectedException())

    def wrap(self, exc: Exception, name: str):
        return exc.err if isinstance(exc, Fail) else DriverException(0x500, f'{self.kind}.{name} failed', exc)

    def responder(self, name: str, attrs: dict):
        attrs.update({'__module__': self.module, '__doc__': f'{self.kind}.{name}'})
        return before(PreProcessRequest(self.maxdev))(type(name.lower(), (), attrs))

    def property(self, name: str, getter, setter=None, field: str | None = None, connected: bool = True):
        """GET returns getter(); PUT calls setter(str value of form field `field`)."""
        rs = self

        def on_get(self, req: Request, resp: Response, devnum: int):
            try:
                if connected:
                    rs.need_connection()
                resp.text = PropertyResponse(getter(), req).json
            except Exception as ex:
                resp.text = PropertyResponse(None, req, rs.wrap(ex, name)).json

        attrs = {'on_get': on_get}
        if setter is not None:
            def on_put(self, req: Request, resp: Response, devnum: int):
                value = get_request_field(field or name, req)        # 400 when missing
                try:
                    if connected:
                        rs.need_connection()
                    setter(value)
                    resp.text = MethodResponse(req).json
                except Exception as ex:
                    resp.text = MethodResponse(req, rs.wrap(ex, name)).json
            attrs['on_put'] = on_put
        return self.responder(name, attrs)

    def method(self, name: str, fn, connected: bool = True):
        """PUT calls fn(req) and returns its value, if any."""
        rs = self

        def on_put(self, req: Request, resp: Response, devnum: int):
            try:
                if connected:
                    rs.need_connection()
                resp.text = MethodResponse(req, value=fn(req)).json
            except Exception as ex:
                resp.text = MethodResponse(req, rs.wrap(ex, name)).json
        return self.responder(name, {'on_put': on_put})
