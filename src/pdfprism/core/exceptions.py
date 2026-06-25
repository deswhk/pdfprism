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


class PageOperationError(PdfPrismError):
    """Raised when a page-level mutation cannot be applied.

    Reasons include invalid rotation angles, attempts to delete every
    page (would leave an empty document), invalid crop rects, or any
    underlying engine error during mutation.
    """


class DocumentSaveError(PdfPrismError):
    """Raised when a document cannot be saved.

    Reasons include I/O errors, permission errors, or engine errors
    during write.
    """
