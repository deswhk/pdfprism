"""Tests for PropertiesService (PR 11)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.properties import PropertiesService

# ---- sanitize_metadata ----


class TestSanitizeMetadata:
    """PropertiesService.sanitize_metadata clears all Info fields and XMP."""

    def test_clears_all_standard_fields(self, mutable_pdf_path: Path) -> None:
        """Positive: every field becomes None after sanitize."""
        import pymupdf

        # Author is populated from Windows user in fixture; also set title
        # so we're clearing at least two fields.
        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata({"title": "Sensitive", "author": "John Doe"})
            raw.save(
                str(mutable_pdf_path),
                incremental=True,
                encryption=pymupdf.PDF_ENCRYPT_KEEP,
            )
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            svc = PropertiesService(adapter)
            svc.sanitize_metadata()
            adapter.save()
        finally:
            adapter.close()

        verify = PyMuPDFAdapter()
        verify.open(mutable_pdf_path)
        try:
            meta = verify.get_metadata()
            for field, value in meta.items():
                assert value is None, f"{field} not cleared: {value!r}"
        finally:
            verify.close()

    def test_delete_xmp_true_calls_adapter(self) -> None:
        """Positive: default delete_xmp=True triggers adapter's delete_xml_metadata."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.get_metadata.return_value = {"title": "x", "author": None}

        svc = PropertiesService(adapter)
        svc.sanitize_metadata()

        adapter.set_metadata.assert_called_once()
        adapter.delete_xml_metadata.assert_called_once()

    def test_delete_xmp_false_skips_xmp_deletion(self) -> None:
        """Positive: delete_xmp=False leaves XMP alone."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.get_metadata.return_value = {"title": "x", "author": None}

        svc = PropertiesService(adapter)
        svc.sanitize_metadata(delete_xmp=False)

        adapter.set_metadata.assert_called_once()
        adapter.delete_xml_metadata.assert_not_called()

    def test_idempotent_on_empty_metadata(self, mutable_pdf_path: Path) -> None:
        """Positive: sanitizing an already-blank doc does not raise."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            svc = PropertiesService(adapter)
            svc.sanitize_metadata()  # first time
            svc.sanitize_metadata()  # second time -- no-op essentially
        finally:
            adapter.close()

    def test_marks_dirty(self, mutable_pdf_path: Path) -> None:
        """Positive: sanitize sets the adapter dirty flag."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.is_dirty is False
            svc = PropertiesService(adapter)
            svc.sanitize_metadata()
            assert adapter.is_dirty is True
        finally:
            adapter.close()


# ---- set_metadata ----


class TestSetMetadataService:
    """PropertiesService.set_metadata passes updates through with normalisation."""

    def test_passes_updates_to_adapter(self) -> None:
        """Positive: adapter.set_metadata is called with the updates."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = PropertiesService(adapter)
        svc.set_metadata({"title": "New Title", "author": "New Author"})
        adapter.set_metadata.assert_called_once()
        call_args = adapter.set_metadata.call_args[0][0]
        assert call_args["title"] == "New Title"
        assert call_args["author"] == "New Author"

    def test_empty_string_normalised_to_none(self) -> None:
        """Positive: empty string from dialog becomes None (clear-field intent)."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = PropertiesService(adapter)
        svc.set_metadata({"title": ""})
        adapter.set_metadata.assert_called_once_with({"title": None})

    def test_none_value_passed_through(self) -> None:
        """Positive: explicit None from caller is passed to adapter as None."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = PropertiesService(adapter)
        svc.set_metadata({"title": None})
        adapter.set_metadata.assert_called_once_with({"title": None})

    def test_partial_update(self, mutable_pdf_path: Path) -> None:
        """Positive: setting only title leaves other fields alone (delegated to adapter)."""
        import pymupdf

        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata({"author": "Keep Me"})
            raw.save(
                str(mutable_pdf_path),
                incremental=True,
                encryption=pymupdf.PDF_ENCRYPT_KEEP,
            )
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            svc = PropertiesService(adapter)
            svc.set_metadata({"title": "New"})
            adapter.save()
        finally:
            adapter.close()

        verify = PyMuPDFAdapter()
        verify.open(mutable_pdf_path)
        try:
            meta = verify.get_metadata()
            assert meta["title"] == "New"
            assert meta["author"] == "Keep Me"
        finally:
            verify.close()

    def test_unknown_keys_delegated_to_adapter(self) -> None:
        """Positive: unknown keys still passed through (adapter filters)."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        svc = PropertiesService(adapter)
        svc.set_metadata({"title": "Real", "unknown_key": "junk"})
        call_args = adapter.set_metadata.call_args[0][0]
        assert "unknown_key" in call_args
        assert "title" in call_args
