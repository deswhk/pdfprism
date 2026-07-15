"""Tests for SecurityService."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import (
    EncryptionOperationError,
    PasswordRequiredError,
)
from pdfprism.services.security import SecurityService

# =========================================================================
# set_password
# =========================================================================


class TestSetPassword:
    """SecurityService.set_password on unencrypted -> encrypted output."""

    def test_unencrypted_gets_password(self, mutable_pdf_path: Path) -> None:
        """Positive: unencrypted + valid password -> in-place save;
        reopen requires the password."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            SecurityService(adapter).set_password("hunter2")
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            verifier.open(mutable_pdf_path)
        verifier.open(mutable_pdf_path, password="hunter2")
        try:
            assert verifier.get_document_info().needs_password is True
        finally:
            verifier.close()

    def test_save_as_different_path_leaves_source_untouched(
        self, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: output_path different from source -> source stays unencrypted."""
        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        try:
            out = tmp_path / "with_password.pdf"
            SecurityService(adapter).set_password("secret", output_path=out)
        finally:
            adapter.close()

        # Target is encrypted
        v_target = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            v_target.open(out)
        v_target.open(out, password="secret")
        v_target.close()

        # Source stays unencrypted
        v_src = PyMuPDFAdapter()
        v_src.open(sample_pdf_path)
        try:
            assert v_src.get_document_info().needs_password is False
        finally:
            v_src.close()

    def test_already_encrypted_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: doc is already encrypted -> EncryptionOperationError."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            with pytest.raises(EncryptionOperationError, match="already encrypted"):
                SecurityService(adapter).set_password("new")
        finally:
            adapter.close()

    def test_empty_password_raises(self, mutable_pdf_path: Path) -> None:
        """Negative: empty string -> EncryptionOperationError."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(EncryptionOperationError, match="empty or whitespace"):
                SecurityService(adapter).set_password("")
        finally:
            adapter.close()

    def test_whitespace_password_raises(self, mutable_pdf_path: Path) -> None:
        """Negative: whitespace-only -> EncryptionOperationError."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(EncryptionOperationError, match="empty or whitespace"):
                SecurityService(adapter).set_password("   ")
        finally:
            adapter.close()


# =========================================================================
# change_password
# =========================================================================


class TestChangePassword:
    """SecurityService.change_password on encrypted -> re-encrypted output."""

    def test_encrypted_gets_new_password(self, encrypted_pdf_path: Path) -> None:
        """Positive: current password fails on output, new one succeeds."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            SecurityService(adapter).change_password("new_password")
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        # Old password should NOT open the changed file
        with pytest.raises(PasswordRequiredError):
            verifier.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        # New password does
        verifier.open(encrypted_pdf_path, password="new_password")
        try:
            assert verifier.get_document_info().needs_password is True
        finally:
            verifier.close()

    def test_unencrypted_raises(self, mutable_pdf_path: Path) -> None:
        """Negative: doc is unencrypted -> EncryptionOperationError."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(EncryptionOperationError, match="not encrypted"):
                SecurityService(adapter).change_password("new")
        finally:
            adapter.close()

    def test_empty_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: empty -> EncryptionOperationError."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            with pytest.raises(EncryptionOperationError, match="empty or whitespace"):
                SecurityService(adapter).change_password("")
        finally:
            adapter.close()

    def test_whitespace_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: whitespace -> EncryptionOperationError."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            with pytest.raises(EncryptionOperationError, match="empty or whitespace"):
                SecurityService(adapter).change_password("\t\n")
        finally:
            adapter.close()


# =========================================================================
# remove_password
# =========================================================================


class TestRemovePassword:
    """SecurityService.remove_password on encrypted -> unencrypted output."""

    def test_encrypted_becomes_unencrypted(self, encrypted_pdf_path: Path) -> None:
        """Positive: encrypted -> save; reopen no longer needs password."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            SecurityService(adapter).remove_password()
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        verifier.open(encrypted_pdf_path)  # no password kwarg
        try:
            assert verifier.get_document_info().needs_password is False
        finally:
            verifier.close()

    def test_save_as_different_path_leaves_source_untouched(
        self, encrypted_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: output_path different from source -> source stays encrypted."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            out = tmp_path / "no_password.pdf"
            SecurityService(adapter).remove_password(output_path=out)
        finally:
            adapter.close()

        # Target is unencrypted
        v_target = PyMuPDFAdapter()
        v_target.open(out)  # no password
        v_target.close()

        # Source stays encrypted
        v_src = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            v_src.open(encrypted_pdf_path)

    def test_unencrypted_raises(self, mutable_pdf_path: Path) -> None:
        """Negative: doc is unencrypted -> EncryptionOperationError."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(EncryptionOperationError, match="not encrypted"):
                SecurityService(adapter).remove_password()
        finally:
            adapter.close()
