"""With the fake pystray: webbrowser.open writes the URL to $FAKE_TRAY_DIR/opened instead of opening it."""
import os
import webbrowser
from pathlib import Path


def _open(url, *args, **kwargs):
    with open(Path(os.environ['FAKE_TRAY_DIR']) / 'opened', 'a') as f:
        f.write(url + '\n')
    return True


webbrowser.open = _open
