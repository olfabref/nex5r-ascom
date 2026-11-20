"""The two Devices together (camera.dev and focuser.dev, created by app.main): which are Connected, and
the camera-app address they talk to."""
import camera
import focuser


def connected() -> list[str]:
    """The Connected Devices by name ('Camera', 'Focuser'), in that order."""
    return [name for name, dev in (('Camera', camera.dev), ('Focuser', focuser.dev)) if dev.connected]


def retarget(url: str):
    """Both Devices talk to camera-app at url from now on (call it while neither is Connected)."""
    camera.dev.retarget(url)
    focuser.dev.retarget(url)
