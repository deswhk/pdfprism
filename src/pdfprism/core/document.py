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

    @property
    def is_dirty(self) -> bool:
        """True when the open document has unsaved mutations.

        Reset to False by ``save``, set to True by any mutation method.
        """
        ...

    def rotate_page(self, index: int, degrees: int) -> None:
        """Rotate the page at ``index`` by 90, 180, or 270 degrees clockwise.

        Rotation is additive to the page's existing rotation; calling
        with 90 twice yields 180.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
            PageOperationError: if ``degrees`` is not 90, 180, or 270.
        """
        ...

    def delete_pages(self, indices: list[int]) -> None:
        """Delete the pages at the given 0-based indices.

        Indices may be in any order; duplicates are deduplicated. The
        adapter sorts and applies deletions in reverse order so earlier
        indices remain valid during the operation.

        Raises:
            PageOutOfRangeError: if any index is outside the document range.
            PageOperationError: if the deletion would leave an empty document.
        """
        ...

    def insert_blank_page(self, index: int, width: float, height: float) -> None:
        """Insert a blank page **before** ``index``.

        Use ``index = page_count`` to append at the end. ``width`` and
        ``height`` are in PDF points (1/72 inch).

        Raises:
            PageOutOfRangeError: if ``index`` is not in [0, page_count].
            PageOperationError: if width or height is not positive.
        """
        ...

    def duplicate_page(self, index: int) -> None:
        """Duplicate the page at ``index``; the copy is inserted right after.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
        """
        ...

    def move_page(self, from_index: int, to_index: int) -> None:
        """Move the page at ``from_index`` to ``to_index``.

        ``to_index`` is interpreted in the **post-removal** coordinate
        space: after the page is removed, it's reinserted before the page
        currently at ``to_index``. ``to_index == page_count - 1`` after
        removal moves the page to the end.

        Raises:
            PageOutOfRangeError: if either index is invalid.
        """
        ...

    def crop_page(
        self,
        index: int,
        margins: tuple[float, float, float, float],
    ) -> None:
        """Crop the page at ``index`` by the given margins.

        Margins are ``(top, right, bottom, left)`` in PDF points,
        each subtracted from the corresponding edge of the page's mediabox.
        Use ``(0, 0, 0, 0)`` to clear an existing crop.

        Raises:
            PageOutOfRangeError: if ``index`` is outside the document range.
            PageOperationError: if margins would yield a zero/negative area.
        """
        ...

    def save(self, path: Path | None = None) -> None:
        """Write the current document state to disk.

        ``path`` defaults to the path the document was opened from
        (in-place save). After a successful save, ``is_dirty`` becomes
        False.

        Raises:
            DocumentSaveError: if the write fails for any reason.
        """
        ...
