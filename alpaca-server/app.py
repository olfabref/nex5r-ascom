# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# app.py - Application module
#
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
# 16-Dec-2022   rbd 0.1 Initial edit for Alpaca sample/template
# 20-Dec-2022   rbd 0.1 Correct endpoint URIs
# 21-Dec-2022   rbd 0.1 Refactor for import protection. Add configurtion.
# 22-Dec-2020   rbd 0.1 Start of logging
# 24-Dec-2022   rbd 0.1 Logging
# 25-Dec-2022   rbd 0.1 Add milliseconds to logger time stamp
# 27-Dec-2022   rbd 0.1 Post-processing logging of request only if not 200 OK
#               MIT License and module header. No multicast on device duh.
# 28-Dec-2022   rbd 0.1 Rename conf.py to config.py to avoid conflict with sphinx
# 30-Dec-2022   rbd 0.1 Device number in /setup routing template. Last chance
#               exception handler, Falcon responder uncaught exeption handler.
# 01-Jan-2023   rbd 0.1 Docstring docs
# 13-Jan-2023   rbd 0.1 More docstring docs. Fix LoggingWSGIRequestHandler,
#               log.logger needs explicit setting in main()
# 23-May-2023   rbd 0.2 GitHub Issue #3 https://github.com/BobDenny/AlpycaDevice/issues/3
#               Corect routing device number capture spelling.
# 23-May-2023   rbd 0.2 Refactoring for  multiple ASCOM device type support
#               GitHub issue #1
# 13-Sep-2024   rbd 1.0 Add support for enum classes within the responder modules
#               GitHub issue #12
# 03-Jan-2025   rbd 1.1 Clarify devices vs device types at import site. Comment only,
#               no logic changes.
#
import argparse                         # nex5r-ascom: --config, --no-tray
import sys
import threading                        # nex5r-ascom: HTTP served beside the tray icon
import traceback
import inspect
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server   # nex5r-ascom: WSGIServer
from socketserver import TCPServer, ThreadingMixIn                              # nex5r-ascom: threaded server
from enum import IntEnum

# -- isort wants the above line to be blank --
# Controller classes (for routing)
import dashboard                        # nex5r-ascom: the Dashboard
import release                          # nex5r-ascom: New Release detection
import tray                             # nex5r-ascom: the tray icon
import update                           # nex5r-ascom: the Update
import discovery
import exceptions
from falcon import Request, Response, App, HTTPInternalServerError
import management
import setup
import log
import config                           # nex5r-ascom: config.load() of the chosen file
from config import Config
from discovery import DiscoveryResponder
from shr import set_shr_logger
from version import __version__         # nex5r-ascom: the Version (ADR 0001)

##############################
# FOR EACH ASCOM DEVICE TYPE #
##############################
import camera                           # nex5r-ascom: the Camera device
import focuser                          # nex5r-ascom: the Focuser device

#--------------
API_VERSION = 1
#--------------

class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """One thread per request: clients poll ImageReady while ImageArray streams (nex5r-ascom change)."""
    daemon_threads = True

    def server_bind(self):
        """HTTPServer.server_bind without socket.getfqdn(): that reverse lookup of the bound address can
        hang for tens of seconds (GitHub macOS runners), before the socket listens (nex5r-ascom change)."""
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
        self.setup_environ()


class LoggingWSGIRequestHandler(WSGIRequestHandler):
    """Subclass of  WSGIRequestHandler allowing us to control WSGI server's logging"""

    def log_message(self, format: str, *args):
        """Log a message from within the Python **wsgiref** simple server

        Logging elsewhere logs the incoming request *before*
        processing in the responder, making it easier to read
        the overall log. The wsgi server calls this function
        at the end of processing. Normally the request would not
        need to be logged again. However, in order to assure
        logging of responses with HTTP status other than
        200 OK, we log the request again here.

        For more info see
        `this article <https://stackoverflow.com/questions/31433682/control-wsgiref-simple-server-log>`_

        Args:
            format  (str):   Unused, old-style format (see notes)
            args[0] (str):   HTTP Method and URI ("request")
            args[1] (str):   HTTP response status code
            args[2] (str):   HTTP response content-length


        Notes:
            * Logs using :py:mod:`log`, our rotating file logger ,
              rather than using stdout.
            * The **format** argument is an old C-style format for
              for producing NCSA Commmon Log Format web server logging.

        """

        ##TODO## If I enable this, the server occasionally fails to respond
        ##TODO## on non-200s, per Wireshark. So crazy!
        #if args[1] != '200':  # Log this only on non-200 responses
        #    log.logger.info(f'{self.client_address[0]} <- {format%args}')

#-----------------------
# Magic routing function
# ----------------------
def init_routes(app: App, devname: str, module):
    """Initialize Falcon routing from URI to responser classses

    Inspects a module and finds all classes, assuming they are Falcon
    responder classes, and calls Falcon to route the corresponding
    Alpaca URI to each responder. This is done by creating the
    URI template from the responder class name.

    Note that it is sufficient to create the controller instance
    directly from the type returned by inspect.getmembers() since
    the instance is saved within Falcon as its resource controller.
    The responder methods are called with an additional 'devno'
    parameter, containing the device number from the URI. Reject
    negative device numbers.

    Args:
        app (App): The instance of the Falcon processor app
        devname (str): The name of the device (e.g. 'rotator")
        module (module): Module object containing responder classes

    Notes:
        * The call to app.add_route() creates the single instance of the
          router class right in the call, as the second parameter.
        * The device number is extracted from the URI by using an
          **int** placeholder in the URI template, and also using
          a format converter to assure that the number is not
          negative. If it is, Falcon will send back an HTTP
          ``400 Bad Request``.

    """

    memlist = inspect.getmembers(module, inspect.isclass)
    for cname,ctype in memlist:
        # Only classes *defined* in the module and not the enum classes
        # nex5r-ascom: only Falcon responders (helper classes such as camera.Fail are skipped)
        if ctype.__module__ == module.__name__ and not issubclass(ctype, IntEnum) \
                and (hasattr(ctype, 'on_get') or hasattr(ctype, 'on_put')):
            app.add_route(f'/api/v{API_VERSION}/{devname}/{{devnum:int(min=0)}}/{cname.lower()}', ctype())  # type() creates instance!


def custom_excepthook(exc_type, exc_value, exc_traceback):
    """Last-chance exception handler

    Caution:
        Hook this as last-chance only after the config info
        has been initiized and the logger is set up!

    Assures that any unhandled exceptions are logged to our logfile.
    Should "never" be called since unhandled exceptions are
    theoretically caught in falcon. Well it's here so the
    exception has a chance of being logged to our file. It's
    used by :py:func:`~app.falcon_uncaught_exception_handler` to
    make sure exception info is logged instead of going to
    stdout.

    Args:
        exc_type (_type_): _description_
        exc_value (_type_): _description_
        exc_traceback (_type_): _description_

    Notes:
        * See the Python docs for `sys.excepthook() <https://docs.python.org/3/library/sys.html#sys.excepthook>`_
        * See `This StackOverflow article <https://stackoverflow.com/a/58593345/159508>`_
        * A config option provides for a full traceback to be logged.

    """
    # Do not print exception when user cancels the program
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    log.logger.error(f'An uncaught {exc_type.__name__} exception occurred:')
    log.logger.error(exc_value)

    if Config.verbose_driver_exceptions and exc_traceback:
        format_exception = traceback.format_tb(exc_traceback)
        for line in format_exception:
            log.logger.error(repr(line))


def falcon_uncaught_exception_handler(req: Request, resp: Response, ex: BaseException, params):
    """Handle Uncaught Exceptions while in a Falcon Responder

        This catches unhandled exceptions within the Falcon responder,
        logging the info to our log file instead of it being lost to
        stdout. Then it logs and responds with a 500 Internal Server Error.

    """
    exc = sys.exc_info()
    custom_excepthook(exc[0], exc[1], exc[2])
    raise HTTPInternalServerError('Internal Server Error', 'Alpaca endpoint responder failed. See logfile.')

# ===========
# APP STARTUP
# ===========
def main(argv: list[str] | None = None):
    """ Application startup"""

    # nex5r-ascom: --config PATH loads the configuration from PATH instead of the user's config.toml
    parser = argparse.ArgumentParser(description='Sony NEX-5R Alpaca server')
    parser.add_argument('--config', metavar='PATH',
                        help=f'configuration file (default: {config.user_config_path()}, '
                             'created from config-template.toml on first launch)')
    # nex5r-ascom: --no-tray runs without the tray / menu bar icon (tests, CI)
    parser.add_argument('--no-tray', action='store_true',
                        help='no icon in the system tray (Windows) or the menu bar (Mac)')
    args = parser.parse_args(argv)
    config.load(args.config)

    logger = log.init_logging()
    # Share this logger throughout
    log.logger = logger
    exceptions.logger = logger
    camera.start_camera_device(logger)
    focuser.start_focuser_device(logger)
    release.start(logger)                   # nex5r-ascom: latest Release at startup, then every 6 h
    discovery.logger = logger
    set_shr_logger(logger)

    #########################
    # FOR EACH ASCOM DEVICE #
    #########################
    camera.logger = logger
    focuser.logger = logger

    # -----------------------------
    # Last-Chance Exception Handler
    # -----------------------------
    sys.excepthook = custom_excepthook

    # ---------
    # DISCOVERY
    # ---------
    _DSC = DiscoveryResponder(Config.ip_address, Config.port)

    # ----------------------------------
    # MAIN HTTP/REST API ENGINE (FALCON)
    # ----------------------------------
    # falcon.App instances are callable WSGI apps
    falc_app = App()
    #
    # Initialize routes for each endpoint the magic way
    #
    #########################
    # FOR EACH ASCOM DEVICE #
    #########################
    init_routes(falc_app, 'camera', camera)
    init_routes(falc_app, 'focuser', focuser)
    #
    # Initialize routes for Alpaca support endpoints
    falc_app.add_route('/management/apiversions', management.apiversions())
    falc_app.add_route(f'/management/v{API_VERSION}/description', management.description())
    falc_app.add_route(f'/management/v{API_VERSION}/configureddevices', management.configureddevices())
    falc_app.add_route('/setup', setup.svrsetup())
    falc_app.add_route(f'/setup/v{API_VERSION}/camera/{{devnum}}/setup', setup.devsetup())
    falc_app.add_route(f'/setup/v{API_VERSION}/focuser/{{devnum}}/setup', setup.devsetup())
    # nex5r-ascom: the Dashboard on the root page
    dashboard.add_routes(falc_app, logger)

    #
    # Install the unhandled exception processor. See above,
    #
    falc_app.add_error_handler(Exception, falcon_uncaught_exception_handler)

    # ------------------
    # SERVER APPLICATION
    # ------------------
    # Using the lightweight built-in Python wsgi.simple_server
    with make_server(Config.ip_address, Config.port, falc_app, server_class=ThreadingWSGIServer,
                     handler_class=LoggingWSGIRequestHandler) as httpd:
        logger.info(f'==STARTUP== nex5r-ascom Alpaca Server Version {__version__}. Serving on {Config.ip_address}:{Config.port}. Time stamps are UTC.')
        # nex5r-ascom: the Update, started from the Dashboard. Once it has launched the installer, it
        # quits as Quit in the tray does (the Alpaca Server shuts down, the icon goes, main returns);
        # without a tray, serve_forever returns. No request is served before this point.
        icon = None

        def quit_for_update():
            if icon and icon.running:
                icon.quit()
            else:
                httpd.shutdown()

        update.start(logger, quit=quit_for_update)
        if args.no_tray:
            # Serve until process is killed
            httpd.serve_forever()
            return
        # nex5r-ascom: the tray icon needs the main thread (AppKit on Mac); HTTP is served on another.
        # Quit in the tray shuts the server down; without a tray, serve until the process is killed.
        serving = threading.Thread(target=httpd.serve_forever, name='http', daemon=True)
        serving.start()
        icon = tray.Tray(tray.dashboard_url(Config.ip_address, Config.port), __version__,
                         quit=httpd.shutdown, checker=release.checker, logger=logger)
        if not icon.run():
            serving.join()

# ========================
if __name__ == '__main__':
    main()
# ========================
