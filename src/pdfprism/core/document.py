"""DocumentAdapter Protocol.

The adapter is the only place that knows about the underlying PDF engine.
Services and UI talk to PDFs exclusively through this interface, so swapping
the engine (e.g., PyMuPDF -> pikepdf + pypdfium2) does not ripple beyond
the adapter package.
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from pdfprism.core.types import DocumentInfo, ExtractedImage, OutlineItem, PageInfo, SearchHit, Word


@runtime_checkable
class DocumentAdapter(Protocol):
    """Operations a PDF engine must provide to support pdfprism.

    Adapters are stateful: a single instance holds at most one open document.
    Call ``open`` before any other method; call ``close`` when done.
    """

    def open(self, path: Path, password: str | None = None) -> None:
        """Open a PDF from disk.

        Raises:
            DocumentOpenError: if the file cannot be opened.
            PasswordRequiredError: if the file is encrypted and no
                (or wrong) password was given.
        """
        ...

    def close(self) -> None:
        """Release engine resources. Idempotent."""
        ...

    @property
    def page_count(self) -> int:
        """Number of pages in the open document."""
        ...

    def get_document_info(self) -> DocumentInfo:
        """Return document-level metadata."""
        ...

    def get_page_info(self, index: int) -> PageInfo:
        """Return per-page metadata for the page at ``index`` (0-based).

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def render_page(self, index: int, zoom: float = 1.0) -> bytes:
        """Render the page at ``index`` to PNG bytes at the given zoom level.

        Zoom of 1.0 produces 72 DPI (the PDF default). 2.0 produces 144 DPI.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def get_outline(self) -> list[OutlineItem]:
        """Return the document outline (table of contents) as a flat list.

        Returns an empty list if the document has no outline. The list is
        in document order; hierarchy is expressed via each item's ``level``.
        """
        ...

    def search_page(self, index: int, term: str) -> list[SearchHit]:
        """Find all matches of ``term`` on the page at ``index`` (0-based).

        Case-insensitive for ASCII characters. Multi-word terms may span
        line breaks. Returns an empty list if there are no matches or if
        ``term`` is empty.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def extract_words(self, index: int) -> list[Word]:
        """Return all words on the page at ``index`` in reading order.

        Coordinates are in PDF page space (1 unit = 1/72 inch, origin
        top-left), the same convention as ``SearchHit``. Used by the
        search service slow path and by rect-based text extraction.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def extract_text(self, index: int) -> str:
        """Return all text on the page at ``index`` in reading order.

        Returns an empty string if the page has no text content (image
        only, blank, etc.). No layout, no font information; for that,
        use ``extract_words``.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def extract_images(self, index: int) -> list[ExtractedImage]:
        """Return all images on the page at ``index`` with raw bytes.

        Returns an empty list if the page has no embedded images.
        Each ``ExtractedImage`` carries the engine xref so duplicates
        across pages can be detected if needed.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...
