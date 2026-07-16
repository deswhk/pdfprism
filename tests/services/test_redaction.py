"""Tests for RedactionService (PR 12)."""

from __future__ import annotations

from unittest.mock import MagicMock

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import Redaction
from pdfprism.services.redaction import RedactionService


class TestAddRedaction:
    """Service constructs a Redaction from args and delegates to adapter."""

    def test_delegates_to_adapter(self) -> None:
        """Positive: service constructs Redaction and calls adapter.add_redaction."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = RedactionService(adapter)

        svc.add_redaction(page_index=0, rect=(10.0, 20.0, 100.0, 40.0))

        adapter.add_redaction.assert_called_once()
        called_with = adapter.add_redaction.call_args[0][0]
        assert isinstance(called_with, Redaction)
        assert called_with.page_index == 0
        assert called_with.rect == (10.0, 20.0, 100.0, 40.0)

    def test_replacement_text_passed_through(self) -> None:
        """Positive: replacement_text kwarg reaches the Redaction."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = RedactionService(adapter)

        svc.add_redaction(
            page_index=0,
            rect=(0.0, 0.0, 10.0, 10.0),
            replacement_text="[REDACTED]",
        )

        called_with = adapter.add_redaction.call_args[0][0]
        assert called_with.replacement_text == "[REDACTED]"

    def test_fill_color_passed_through(self) -> None:
        """Positive: fill_color kwarg reaches the Redaction."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = RedactionService(adapter)

        svc.add_redaction(
            page_index=0,
            rect=(0.0, 0.0, 10.0, 10.0),
            fill_color=(64, 64, 64),
        )

        called_with = adapter.add_redaction.call_args[0][0]
        assert called_with.fill_color == (64, 64, 64)


class TestListRedactions:
    def test_delegates_to_adapter(self) -> None:
        """Positive: service returns adapter's list_redactions output."""
        expected = [Redaction(page_index=0, rect=(0.0, 0.0, 10.0, 10.0))]
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.list_redactions.return_value = expected

        svc = RedactionService(adapter)
        got = svc.list_redactions()

        assert got == expected
        adapter.list_redactions.assert_called_once()


class TestRemoveRedaction:
    def test_delegates_to_adapter(self) -> None:
        """Positive: service passes page_index + redaction_index to adapter."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = RedactionService(adapter)

        svc.remove_redaction(page_index=0, redaction_index=2)

        adapter.remove_redaction.assert_called_once_with(0, 2)


class TestApply:
    def test_returns_count_from_adapter(self) -> None:
        """Positive: apply() returns whatever adapter.apply_redactions returned."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.apply_redactions.return_value = 5

        svc = RedactionService(adapter)
        assert svc.apply() == 5

    def test_zero_pending_returns_zero(self) -> None:
        """Positive: nothing pending -> zero."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.apply_redactions.return_value = 0

        svc = RedactionService(adapter)
        assert svc.apply() == 0
