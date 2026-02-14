"""
Logging configuration for tax document processor.
Provides centralized logging with file and console handlers.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.logging import RichHandler

# Global logger registry
_loggers: dict[str, logging.Logger] = {}


def setup_logger(
    name: str = "tax_processor",
    level: str = "INFO",
    log_file: Optional[str] = None,
    use_rich: bool = True,
) -> logging.Logger:
    """
    Set up and configure a logger.
    
    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
        use_rich: Whether to use Rich handler for console output
    
    Returns:
        Configured logger instance
    """
    # Return existing logger if already configured
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.handlers.clear()  # Clear any existing handlers
    
    # Console handler
    if use_rich:
        console_handler = RichHandler(
            show_time=True,
            show_path=True,
            markup=True,
            rich_tracebacks=True,
        )
        console_handler.setLevel(logging.DEBUG)
        console_format = logging.Formatter("%(message)s")
        console_handler.setFormatter(console_format)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_format)
    
    logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Store in registry
    _loggers[name] = logger
    
    return logger


def get_logger(name: str = "tax_processor") -> logging.Logger:
    """
    Get an existing logger or create a default one.
    
    Args:
        name: Logger name
    
    Returns:
        Logger instance
    """
    if name in _loggers:
        return _loggers[name]
    
    # Create a default logger if not found
    return setup_logger(name)


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter to mask sensitive data like SSNs and EINs.
    """
    
    SENSITIVE_PATTERNS = [
        # SSN pattern: XXX-XX-XXXX
        (r"\b\d{3}-\d{2}-\d{4}\b", "***-**-****"),
        # EIN pattern: XX-XXXXXXX
        (r"\b\d{2}-\d{7}\b", "**-*******"),
        # Account numbers (generic)
        (r"\b\d{10,}\b", "**********"),
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and mask sensitive data in log messages."""
        import re
        
        message = record.getMessage()
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            message = re.sub(pattern, replacement, message)
        
        # Update the record's message
        record.msg = message
        record.args = ()
        
        return True