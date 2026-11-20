"""NEX-5R lens focus behind the Alpaca Focuser responders (focuser.py).

The camera only offers CameraEx.shiftFocusPosition(offset): an ABSOLUTE offset in -16..16 from a
reference point, which an autofocus sets (and must precede any offset, or the camera freezes). The
focuser is therefore absolute, positions 0..32 = offsets -16..16, position 16 = where the lens was at
the last autofocus ("arming"). Re-arming moves the reference: positions before and after do not match.

Default arming (tested 2026-11-20): autofocus in focus-mode manual, which arms without moving the lens,
then focus-mode auto, where the offsets move it. Position 16 is then wherever the lens was focused by
hand. An autofocus in auto would also arm, but moves the lens first.
"""
import threading
from logging import Logger

from nex5r import CameraError, Nex5r


class FocuserDevice:
    def __init__(self, logger: Logger, url: str, arm_mode: str, drive_mode: str, arm_on_connect: bool):
        self.logger = logger
        self.cam = Nex5r(url)
        self.arm_mode = arm_mode
        self.drive_mode = drive_mode
        self.arm_on_connect = arm_on_connect
        self._lock = threading.Lock()
        self.connected = False
        self.min_offset = -16
        self.max_offset = 16
        self.offset = 0
        self.armed = False
        self.is_moving = False
        self.error: str | None = None

    @property
    def max_step(self) -> int:
        return self.max_offset - self.min_offset

    @property
    def position(self) -> int:
        return self.offset - self.min_offset

    def _apply(self, st: dict):
        try:
            self.min_offset = int(st.get('min', self.min_offset))
            self.max_offset = int(st.get('max', self.max_offset))
            self.offset = int(st.get('offset', self.offset))
        except ValueError:
            raise CameraError(f'unexpected focus state {st}')
        self.armed = st.get('armed') == 'true'

    def connect(self):
        self._apply(self.cam.focus())                 # raises CameraError when unreachable
        if not self.armed and self.arm_on_connect:
            self.arm()
        self.connected = True
        self.logger.info(f'[focuser] connected: offset {self.offset} (position {self.position}), '
                         f'armed {self.armed}')

    def disconnect(self):
        self.connected = False

    def arm(self, mode: str | None = None):
        """Camera autofocus in `mode` (default arm_mode), then focus-mode drive_mode: arms the offsets;
        the lens position after the autofocus becomes position 16."""
        with self._lock:
            if self.is_moving:
                raise RuntimeError('the focuser is moving')
            m = self.arm_mode if mode is None else mode
            self.logger.info(f'[focuser] arming: autofocus in {m or "the current focus mode"}'
                             + (f', then focus mode {self.drive_mode}' if self.drive_mode else ''))
            self._apply(self.cam.focus_arm(m))
            if self.drive_mode:
                self._apply(self.cam.focus_mode(self.drive_mode))

    def move(self, position: int):
        """Starts a move to `position` (0..max_step); returns at once, is_moving until done."""
        with self._lock:
            if self.is_moving:
                raise RuntimeError('the focuser is already moving')
            if not self.armed:
                self._apply(self.cam.focus())         # the app may have been relaunched
                if not self.armed:
                    raise RuntimeError('focus not armed: connect again, or Action "arm"')
            self.is_moving = True
            self.error = None
        threading.Thread(target=self._run, args=(position + self.min_offset,), daemon=True).start()

    def _run(self, offset: int):
        try:
            self._apply(self.cam.focus_move(offset))
            self.logger.info(f'[focuser] at position {self.position} (offset {self.offset})')
        except Exception as e:
            self.error = str(e)
            self.logger.error(f'[focuser] move failed: {e}')
            try:
                self._apply(self.cam.focus())
            except Exception:
                pass
        finally:
            self.is_moving = False
