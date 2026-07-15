"""Encryption service (PR 10.5).

Named intents wrapping ``PyMuPDFAdapter.save(encryption=...)``:
``set_password``, ``change_password``, ``remove_password``. Each
validates the caller's intent against the document's current state
before delegating to the adapter, so mismatched intents fail fast
without touching disk.

For the raw primitive (arbitrary ``EncryptionSpec`` on save), callers
still use the adapter directly. This service is for the *intent-level*
UI-facing operations.
"""

from __future__ import annotations

from pathlib import Path

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import EncryptionOperationError
from pdfprism.core.types import EncryptionSpec


class SecurityService:
    """Encryption operations at the intent level.

    Constructed with a bound ``PyMuPDFAdapter`` (matching ``PageService``).
    Every method validates the current document state before invoking
    ``adapter.save`` with the appropriate ``EncryptionSpec``.
    """

    def __init__(self, adapter: PyMuPDFAdapter) -> None:
        self._adapter = adapter

    # ---- Public intents ---------------------------------------------------

    def set_password(self, new_password: str, output_path: Path | None = None) -> None:
        """Add a password to an unencrypted document.

        Args:
            new_password: the password to apply. Must be non-empty and
                not whitespace-only.
            output_path: destination. ``None`` saves in-place over the
                document's original path.

        Raises:
            EncryptionOperationError: if the document is already
                encrypted (use ``change_password`` instead), or the
                password fails ``_validate_password`` (empty /
                whitespace-only).
            DocumentSaveError: propagated from the adapter on I/O failure.
        """
        if self._is_encrypted():
            raise EncryptionOperationError(
                "Document is already encrypted; use change_password instead."
            )
        self._validate_password(new_password)
        self._adapter.save(
            output_path,
            encryption=EncryptionSpec(user_password=new_password),
        )

    def change_password(self, new_password: str, output_path: Path | None = None) -> None:
        """Change the password on an already-encrypted document.

        The document must already be authenticated (opened successfully).
        ``new_password`` replaces the current one on the output file.

        Raises:
            EncryptionOperationError: if the document is not currently
                encrypted (use ``set_password`` instead), or the new
                password is invalid.
            DocumentSaveError: propagated from the adapter.
        """
        if not self._is_encrypted():
            raise EncryptionOperationError("Document is not encrypted; use set_password instead.")
        self._validate_password(new_password)
        self._adapter.save(
            output_path,
            encryption=EncryptionSpec(user_password=new_password),
        )

    def remove_password(self, output_path: Path | None = None) -> None:
        """Remove the password from an encrypted document.

        Raises:
            EncryptionOperationError: if the document is not currently
                encrypted (nothing to remove).
            DocumentSaveError: propagated from the adapter.
        """
        if not self._is_encrypted():
            raise EncryptionOperationError("Document is not encrypted; nothing to remove.")
        self._adapter.save(
            output_path,
            encryption=EncryptionSpec(user_password=None),
        )

    # ---- Internals -------------------------------------------------------

    def _is_encrypted(self) -> bool:
        """True if the current document requires (or required) a password."""
        return self._adapter.get_document_info().needs_password

    @staticmethod
    def _validate_password(password: str) -> None:
        """Raise EncryptionOperationError for empty or whitespace-only input.

        No length or complexity requirements -- password strength is
        the user's responsibility, not the library's.
        """
        if not password or not password.strip():
            raise EncryptionOperationError("Password must not be empty or whitespace-only.")
