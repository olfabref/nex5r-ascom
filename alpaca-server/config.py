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
import sys
import toml
import logging

_dict = {}
_dict = toml.load(f'{sys.path[0]}/config.toml')    # Errors here are fatal.
_dict2 = {}
try:
    # ltf - this file, if it exists can override or supplement definitions
    # in the normal config.toml. This facilitates putting the driver in a
    # docker container where installation specific configuration can be
    # put in a file that isn't pulled from a repository
    _dict2 = toml.load('/alpyca/config.toml')
except:
    _dict2 = {}
    # file is optional so it's ok if it isn't there

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
        ``./config.toml`` (the default settings file).
    """
    # ---------------
    # Network Section
    # ---------------
    ip_address: str = get_toml('network', 'ip_address')
    port: int = get_toml('network', 'port')
    # --------------
    # Server Section
    # --------------
    location: str = get_toml('server', 'location')
    verbose_driver_exceptions: bool = get_toml('server', 'verbose_driver_exceptions')
    # --------------
    # Device Section
    # --------------
    camera_url: str = get_toml('device', 'camera_url')
    sensor_x: int = get_toml('device', 'sensor_x')
    sensor_y: int = get_toml('device', 'sensor_y')
    pixel_size_um: float = get_toml('device', 'pixel_size_um')
    max_adu: int = get_toml('device', 'max_adu')
    bayer_offset_x: int = get_toml('device', 'bayer_offset_x')
    bayer_offset_y: int = get_toml('device', 'bayer_offset_y')
    sensor_mono: bool = get_toml('device', 'sensor_type') == 'mono'
    exposure_min: float = get_toml('device', 'exposure_min')
    exposure_max: float = get_toml('device', 'exposure_max')
    file_timeout: float = get_toml('device', 'file_timeout')
    focus_arm_mode: str = get_toml('focuser', 'arm_mode')
    focus_drive_mode: str = get_toml('focuser', 'drive_mode')
    focus_arm_on_connect: bool = get_toml('focuser', 'arm_on_connect')
    log_level: int = logging.getLevelName(get_toml('logging', 'log_level'))  # Not documented but works (!!!!)
    log_to_stdout: str = get_toml('logging', 'log_to_stdout')
    max_size_mb: int = get_toml('logging', 'max_size_mb')
    num_keep_logs: int = get_toml('logging', 'num_keep_logs')
