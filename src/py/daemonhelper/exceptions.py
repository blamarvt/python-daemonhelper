"""
exceptions.py

All classes/definitions in this file should pertain to custom exceptions
for the python-daemonhelper project.
"""

class DaemonStopped(Exception):
    """
    Raised when the daemon is stopped.
    """
    def __init__(self):
        Exception.__init__(self, "Daemon is not running")

class DaemonRunning(Exception):
    """
    Raised when the daemon is started.
    """
    def __init__(self):
        Exception.__init__(self, "Daemon is running")
