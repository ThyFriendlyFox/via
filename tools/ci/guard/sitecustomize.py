"""Python loads this file at the start of every process that has this folder on PYTHONPATH.

It installs engine_watch (beside it), then runs the next sitecustomize.py on sys.path, the one this
file hides: a Python build may ship its own (this machine's fixes the zlib module).
"""

import importlib.util
import os
import sys

import engine_watch

engine_watch.install()

_here = os.path.dirname(os.path.abspath(__file__))
for _entry in sys.path:
    _file = os.path.join(_entry or os.getcwd(), "sitecustomize.py")
    if os.path.abspath(_entry or os.getcwd()) != _here and os.path.isfile(_file):
        _spec = importlib.util.spec_from_file_location("_next_sitecustomize", _file)
        _next = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_next)
        break
