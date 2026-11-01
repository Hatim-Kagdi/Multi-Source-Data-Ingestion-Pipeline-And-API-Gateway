"""Structured logging configuration module.

Provides unified logging format across application services, background tasks,
and external communication clients.
"""

import logging
import sys
from typing import Optional
from app.core.config import get_settings


class StructuredFormatter(logging.Formatter):
    """Custom formatter producing readable structured logs with component markers."""

    COLOR_CODES = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET_CODE = "\033[0m"

    def __init__(self, use_colors: bool = False) -> None:
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        name = record.name
        message = record.getMessage()

        if self.use_colors and level in self.COLOR_CODES:
            colored_level = f"{self.COLOR_CODES[level]}{level:<8}{self.RESET_CODE}"
        else:
            colored_level = f"{level:<8}"

        formatted = f"[{timestamp}] [{colored_level}] [{name}] {message}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted


def setup_logging(log_level: Optional[str] = None) -> None:
    """Initialize root and application loggers with structured formatting."""
    settings = get_settings()
    level_name = (log_level or settings.LOG_LEVEL).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    # Determine whether terminal supports color
    use_colors = sys.stdout.isatty() and settings.ENVIRONMENT != "production"

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to prevent duplicate lines
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(StructuredFormatter(use_colors=use_colors))
    root_logger.addHandler(console_handler)

    # Lower noisy 3rd-party loggers if not in debug
    if not settings.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a structured logger instance for a given module name."""
    return logging.getLogger(name)

