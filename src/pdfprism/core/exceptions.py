"""Exceptions raised by the pdfprism core layer."""


class PdfPrismError(Exception):
    """Base class for all pdfprism errors."""


class DocumentOpenError(PdfPrismError):
    """Raised when a PDF cannot be opened.

    Reasons include file-not-found, not a valid PDF, a corrupt file,
    or a password-protected file opened without a valid password.
    """


class PasswordRequiredError(DocumentOpenError):
    """Raised when a PDF requires a password to open."""


class PageOutOfRangeError(PdfPrismError):
    """Raised when a page index is outside the document's range."""
