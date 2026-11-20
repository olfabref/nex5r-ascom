# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# conf.py - Device configuration file and shared logger construction
# Part of the AlpycaDevice Alpaca skeleton/template device driver
#
# Author:   Robert B. Denny <rdenny@dc3.com> (rbd)
#
# Python Compatibility: Requires Python 3.7 or later
# GitHub: https://github.com/ASCOMInitiative/AlpycaDevice
#
# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2022-2024 Bob Denny
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------
# Edit History:
# 24-Dec-2022   rbd 0.1 Logging
# 25-Dec-2022   rbd 0.1 More config items, separate logging section
# 27-Dec-2022   rbd 0.1 Move shared logger construction and global
#               var here. MIT license and module header. No mcast.
# 17-Feb-2024   ltf 0.6 GitHub PR #11 "docker friendly configuration"
#               https://github.com/ASCOMInitiative/AlpycaDevice/pull/11
#               (manually merged). Remove comment about "slimy hack".
# 20-Ferb-2024  rbd 0.7 Add sync_write_connected to control sync/async
#               write-Connected behavior.
#
# nex5r-ascom: the configuration can be loaded from an explicit path (load(), app.py --config);
#               without one, config.toml in the user folder, created from config-template.toml
#               on first launch so that a reinstall or an Update does not overwrite it (ADR 0002).
#
import os
import shutil
import sys
import toml
import logging
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent / 'config-template.toml'
OVERRIDE_PATH = '/alpyca/config.toml'

_dict = {}
_dict2 = {}

def get_toml(sect: str, item: str):
    setting = ''
    s = None
    try:
        setting = _dict2[sect][item]
    except:
        try:
            setting = _dict[sect][item]
        except:
            setting = ''
    return setting

class Config:
    """Device configuration. For docker based installation specific
        configuration, will first look for ``/alpyca/config.toml``
        and if exists, any setting there will override those in
        the user's ``config.toml`` (the default settings file), or in the
        file given to :py:func:`load`.
    """
    # Set by load(), see there.
    ip_address: str
    port: int
    location: str
    verbose_driver_exceptions: bool
    camera_url: str
    sensor_x: int
    sensor_y: int
    pixel_size_um: float
    max_adu: int
    bayer_offset_x: int
    bayer_offset_y: int
    sensor_mono: bool
    exposure_min: float
    exposure_max: float
    file_timeout: float
    focus_arm_mode: str
    focus_drive_mode: str
    focus_arm_on_connect: bool
    log_level: int
    log_to_stdout: str
    max_size_mb: int
    num_keep_logs: int


def user_config_path() -> Path:
    """config.toml in the user folder: %APPDATA% on Windows, ~/Library/Application Support on Mac,
    $XDG_CONFIG_HOME (default ~/.config) elsewhere."""
    if sys.platform == 'win32':
        base = Path(os.environ['APPDATA'])
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'nex5r-ascom' / 'config.toml'


def ensure_user_config() -> Path:
    """The user's config.toml, copied from the template first if it does not exist yet."""
    path = user_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATE_PATH, path)
    return path


def load(path: str | Path | None = None):
    """(Re)loads :py:class:`Config` from ``path`` (default: the user's config.toml, see
    :py:func:`ensure_user_config`)."""
    global _dict, _dict2
    _dict = toml.load(path or ensure_user_config())     # Errors here are fatal.
    try:
        # ltf - this file, if it exists can override or supplement definitions
        # in the normal config.toml. This facilitates putting the driver in a
        # docker container where installation specific configuration can be
        # put in a file that isn't pulled from a repository
        _dict2 = toml.load(OVERRIDE_PATH)
    except:
        _dict2 = {}
        # file is optional so it's ok if it isn't there
    c = Config
    # ---------------
    # Network Section
    # ---------------
    c.ip_address = get_toml('network', 'ip_address')
    c.port = get_toml('network', 'port')
    # --------------
    # Server Section
    # --------------
    c.location = get_toml('server', 'location')
    c.verbose_driver_exceptions = get_toml('server', 'verbose_driver_exceptions')
    # --------------
    # Device Section
    # --------------
    c.camera_url = get_toml('device', 'camera_url')
    c.sensor_x = get_toml('device', 'sensor_x')
    c.sensor_y = get_toml('device', 'sensor_y')
    c.pixel_size_um = get_toml('device', 'pixel_size_um')
    c.max_adu = get_toml('device', 'max_adu')
    c.bayer_offset_x = get_toml('device', 'bayer_offset_x')
    c.bayer_offset_y = get_toml('device', 'bayer_offset_y')
    c.sensor_mono = get_toml('device', 'sensor_type') == 'mono'
    c.exposure_min = get_toml('device', 'exposure_min')
    c.exposure_max = get_toml('device', 'exposure_max')
    c.file_timeout = get_toml('device', 'file_timeout')
    c.focus_arm_mode = get_toml('focuser', 'arm_mode')
    c.focus_drive_mode = get_toml('focuser', 'drive_mode')
    c.focus_arm_on_connect = get_toml('focuser', 'arm_on_connect')
    c.log_level = logging.getLevelName(get_toml('logging', 'log_level'))  # Not documented but works (!!!!)
    c.log_to_stdout = get_toml('logging', 'log_to_stdout')
    c.max_size_mb = get_toml('logging', 'max_size_mb')
    c.num_keep_logs = get_toml('logging', 'num_keep_logs')
