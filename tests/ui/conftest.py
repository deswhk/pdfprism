"""Shared fixtures for UI-layer tests.

Ensures a ``QApplication`` exists for every UI test. Tests that don't use
``qtbot`` directly (e.g. PageCache tests that still construct ``QPixmap``)
need this because ``QPaintDevice`` requires an application instance.
"""

import pytest


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    """Auto-applied: makes pytest-qt's QApplication available everywhere."""
    yield qapp
