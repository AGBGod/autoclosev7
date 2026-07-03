"""
logger_setup.py
----------------
Zentrale Logging-Konfiguration fuer AutoCloseV7.
Schreibt Logeintraege sowohl in eine rotierende Logdatei als auch (optional) in die Konsole.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from src.paths import get_log_dir


def setup_logging(level: int = logging.INFO, console: bool = True) -> logging.Logger:
    """
    Richtet das zentrale Logging fuer die Anwendung ein.

    - Rotierende Logdatei (max. 1 MB, 5 Backups), damit die Festplatte nicht vollaeuft.
    - Optionale Ausgabe auf der Konsole zum Debuggen.
    """
    log_file = os.path.join(get_log_dir(), "autoclosev7.log")

    logger = logging.getLogger("AutoCloseV7")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        # Verhindert doppelte Handler bei mehrfachem Aufruf (z. B. in Tests).
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
