"""
Standardized logging configuration for Cloud Functions.
"""

import logging
import os
import sys
import time


class MillisecondFormatter(logging.Formatter):
    """Formatter that includes milliseconds in timestamps."""

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
            if "%f" in datefmt:
                milliseconds = int((record.created % 1) * 1000)
                s = s.replace("%f", f"{milliseconds:03d}")
            return s

        t = time.strftime(self.default_time_format, ct)
        if self.default_msec_format:
            t = self.default_msec_format % (t, record.msecs)
        return t


def setup_root_logging(level_override=None):
    """Configure the root logger for use without explicit logger creation."""
    debug_flag = str(os.environ.get("DEBUG", "")).lower() in ("1", "true", "yes")
    if level_override:
        level_str = level_override.upper()
    else:
        level_str = os.environ.get("LOG_LEVEL", "DEBUG" if debug_flag else "INFO").upper()

    log_level = getattr(logging, level_str, logging.INFO)

    formatter = MillisecondFormatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logging.root.setLevel(log_level)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)

    if log_level > logging.DEBUG:
        for lib in ("google", "google.cloud", "urllib3", "requests"):
            logging.getLogger(lib).setLevel(logging.WARNING)
