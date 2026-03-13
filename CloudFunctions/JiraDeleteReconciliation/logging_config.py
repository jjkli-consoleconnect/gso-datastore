"""
Standardized logging configuration for Jira pipelines (Cloud Functions version).
Provides consistent formatting and level control across all scripts.
"""
import logging
import os
import sys
import time


class MillisecondFormatter(logging.Formatter):
    """Custom formatter that includes milliseconds in timestamps."""
    
    def formatTime(self, record, datefmt=None):
        """Format time with milliseconds."""
        ct = self.converter(record.created)
        if datefmt:
            fmt = datefmt
            # Python's time.strftime does not support %f on all platforms.
            # Replace %f with computed milliseconds before strftime.
            if '%f' in fmt:
                milliseconds = int((record.created % 1) * 1000)
                fmt = fmt.replace('%f', f'{milliseconds:03d}')
            s = time.strftime(fmt, ct)
            return s
        else:
            t = time.strftime(self.default_time_format, ct)
            if self.default_msec_format:
                t = self.default_msec_format % (t, record.msecs)
            return t


def setup_logging(logger_name="jira_pipeline", level_override=None):
    """
    Configure logging with consistent format across all pipelines.
    
    Args:
        logger_name: Name for the logger (used in logs)
        level_override: Force a specific level (DEBUG, INFO, etc.) - overrides env var
    
    Returns:
        Configured logger instance
    """
    # Determine log level: explicit > env var > default INFO
    if level_override:
        log_level_str = level_override.upper()
    else:
        log_level_str = os.environ.get('LOG_LEVEL', 'INFO').upper()
    
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Check DEBUG flag for backward compatibility
    debug_flag = str(os.environ.get('DEBUG', '')).lower() in ('1', 'true', 'yes')
    if debug_flag:
        log_level = logging.DEBUG
    
    # Configure logger with custom millisecond formatter
    formatter = MillisecondFormatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S.%f')
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.handlers.clear()  # Remove any existing handlers
    logger.addHandler(handler)
    
    # Suppress noisy third-party loggers when not debugging
    if log_level > logging.DEBUG:
        for lib in ('google', 'google.cloud', 'urllib3', 'requests'):
            logging.getLogger(lib).setLevel(logging.WARNING)
    
    return logger


# Convenience: also configure the root logger
def setup_root_logging(level_override=None):
    """Configure the root logger for use without explicit logger creation."""
    debug_flag = str(os.environ.get('DEBUG', '')).lower() in ('1', 'true', 'yes')
    if level_override:
        level_str = level_override.upper()
    else:
        level_str = os.environ.get('LOG_LEVEL', 'DEBUG' if debug_flag else 'INFO').upper()
    
    log_level = getattr(logging, level_str, logging.INFO)
    
    formatter = MillisecondFormatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S.%f')
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    logging.root.setLevel(log_level)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    
    # Suppress third-party loggers
    if log_level > logging.DEBUG:
        for lib in ('google', 'google.cloud', 'urllib3', 'requests'):
            logging.getLogger(lib).setLevel(logging.WARNING)
