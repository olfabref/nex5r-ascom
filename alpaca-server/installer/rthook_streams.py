# PyInstaller runtime hook: a windowed (console=False) executable has sys.stdout and sys.stderr set to
# None, and the logging stdout handler or wsgiref's error output would then fail. Send them to devnull.
import os
import sys

for _name in ('stdout', 'stderr'):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, 'w', encoding='utf-8'))
