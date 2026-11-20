"""A fake pystray, put first on the Alpaca Server's PYTHONPATH by tests/test_tray.py.

Instead of drawing an icon it writes what the tray shows to $FAKE_TRAY_DIR/tray.json (title, visible
menu entries, icon size) whenever that changes, and clicks the menu entry whose text a test writes to
$FAKE_TRAY_DIR/click. FAKE_TRAY_FAIL=1 makes run() fail as on a machine without a tray.
"""
import json
import os
import threading
import time
from pathlib import Path

OUT = Path(os.environ['FAKE_TRAY_DIR'])


def _text(item):
    return item.text(item) if callable(item.text) else item.text


class MenuItem:
    def __init__(self, text, action=None, default=False, enabled=True, visible=True):
        self.text, self.action, self.default = text, action, default
        self.enabled, self.visible = enabled, visible

    def _visible(self):
        return self.visible(self) if callable(self.visible) else self.visible


class Menu:
    SEPARATOR = MenuItem('-')

    def __init__(self, *items):
        self.items = items


class Icon:
    def __init__(self, name, icon=None, title=None, menu=None):
        self.name, self._icon, self._title, self.menu = name, icon, title, menu
        self._stopped = threading.Event()
        self._lock = threading.Lock()

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        self._title = value
        self._dump()

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value):
        self._icon = value
        self._dump()

    def update_menu(self):
        self._dump()

    def _items(self):
        return [i for i in self.menu.items if i is not Menu.SEPARATOR and i._visible()]

    def _dump(self):
        state = {'title': self._title, 'icon_size': list(self._icon.size) if self._icon else None,
                 'menu': [_text(i) for i in self._items()],
                 'default': [_text(i) for i in self._items() if i.default]}
        with self._lock:
            tmp = OUT / 'tray.json.tmp'
            tmp.write_text(json.dumps(state))
            tmp.replace(OUT / 'tray.json')

    def run(self, setup=None):
        if os.environ.get('FAKE_TRAY_FAIL'):
            raise RuntimeError('no system tray on this machine')
        self._dump()
        if setup:
            threading.Thread(target=setup, args=(self,), daemon=True).start()
        click = OUT / 'click'
        while not self._stopped.is_set():
            if click.exists():
                text = click.read_text()
                click.unlink()
                item = next(i for i in self._items() if _text(i) == text)
                item.action(self, item)
            time.sleep(0.05)

    def stop(self):
        self._stopped.set()
