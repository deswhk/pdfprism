"""Stdlib logging configuration for pdfprism.

Call ``configure()`` exactly once at application startup. Modules elsewhere
should use ``logger = logging.getLogger(__name__)`` and standard calls
(``logger.info()``, ``logger.error()``, ``logger.exception()``).
"""

import logging
import logging.handlers
from pathlib import Path

_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10_000_000  # 10 MB per file
_BACKUP_COUNT = 5


def configure(log_dir: Path, level: int = logging.INFO) -> None:
    """Configure the ``pdfprism`` logger with rotating file + console handlers.

    File handler writes to ``<log_dir>/pdfprism.log``, rotates at 10 MB,
    keeps 5 backups. Console handler writes to stderr at the same level.
    Idempotent: safe to call more than once (handlers are reset each call).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "pdfprism.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    root = logging.getLogger("pdfprism")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False
