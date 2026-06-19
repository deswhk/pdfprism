"""Application entry point."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtWidgets import QApplication

from pdfprism.config import APP_NAME, ORG_DOMAIN, ORG_NAME
from pdfprism.logging_config import configure as configure_logging
from pdfprism.ui.main_window import MainWindow


def _resolve_log_dir() -> Path:
    """Return the log directory.

    In development (editable install with a pyproject.toml findable by
    walking up from this file), logs go to ``<project>/logs/``. When
    installed without source available, fall back to the OS-standard app
    data location (e.g., ``%LOCALAPPDATA%/pdfprism/`` on Windows).
    """
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent / "logs"
    base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    return base / "logs"


def main() -> int:
    """Application entry point. Returns the Qt event loop exit code."""
    configure_logging(_resolve_log_dir())
    logger = logging.getLogger(__name__)
    logger.info("Starting %s", APP_NAME)

    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setOrganizationDomain(ORG_DOMAIN)
    QCoreApplication.setApplicationName(APP_NAME)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logger.info("Exiting with code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
