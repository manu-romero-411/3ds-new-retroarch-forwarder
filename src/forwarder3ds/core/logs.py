"""Logging setup with short coloured tags: ``[INFO]``, ``[ OK ]``, ``[WARN]``, ``[ERR ]``."""

from __future__ import annotations

import logging
import sys

SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")

LOGGER_NAME = "forwarder3ds"

_TAGS = {
    logging.DEBUG: ("[DBG ]", "\033[2m"),
    logging.INFO: ("[INFO]", "\033[36m"),
    SUCCESS: ("[ OK ]", "\033[32m"),
    logging.WARNING: ("[WARN]", "\033[33m"),
    logging.ERROR: ("[ERR ]", "\033[31m"),
    logging.CRITICAL: ("[ERR ]", "\033[1;31m"),
}
_RESET = "\033[0m"


def get_logger(name: str = "") -> logging.Logger:
    """Return the package logger or one of its children."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def log_success(logger: logging.Logger, message: str, *args: object) -> None:
    """Log ``message`` at the custom SUCCESS level."""
    logger.log(SUCCESS, message, *args)


class TagFormatter(logging.Formatter):
    """``[TAG] yyyy-mm-dd_hh:mm:ss message`` with optional ANSI colours."""

    def __init__(self, colour: bool) -> None:
        super().__init__(datefmt="%Y-%m-%d_%H:%M:%S")
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        tag, colour = _TAGS.get(record.levelno, ("[????]", ""))
        stamp = self.formatTime(record, self.datefmt)
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if self._colour:
            tag = f"{colour}{tag}{_RESET}"
        return f"{tag} {stamp} {message}"


def setup_console_logging(verbose: bool = False) -> None:
    """Attach a stderr handler to the package logger (idempotent)."""
    logger = get_logger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in logger.handlers:
        if getattr(handler, "_forwarder3ds_console", False):
            handler.setLevel(logger.level)
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(TagFormatter(colour=sys.stderr.isatty()))
    handler.setLevel(logger.level)
    setattr(handler, "_forwarder3ds_console", True)
    logger.addHandler(handler)
    logger.propagate = False
