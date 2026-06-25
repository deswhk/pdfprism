"""Page-operation service.

Thin wrapper around the adapter's mutation methods, named after user intent.
Lives at the service layer so:

- UI code stays out of the adapter directly (parallels SearchService/ExtractService).
- Operations are testable without Qt.
- PR 8.5 cross-doc operations (extract-to-file, insert-from, split,
  free function merge) live here alongside the single-doc primitives.
- Future composite operations (PR 11 redaction → crop) have a place to live.

All operations mutate the bound adapter in place and set its dirty flag.
Index validation is delegated to the adapter; see ``DocumentAdapter`` for
the exception contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.document import DocumentAdapter


class PageService:
    """Page-level mutation operations on a single bound document."""

    def __init__(self, adapter: DocumentAdapter) -> None:
        self._adapter = adapter

    # ---- Single-page rotations ------------------------------------------------

    def rotate_page(self, index: int, degrees: int) -> None:
        """Rotate page ``index`` clockwise by 90, 180, or 270 degrees."""
        self._adapter.rotate_page(index, degrees)

    def rotate_left(self, index: int) -> None:
        """Rotate page ``index`` 90 degrees counter-clockwise (i.e. 270 CW)."""
        self._adapter.rotate_page(index, 270)

    def rotate_right(self, index: int) -> None:
        """Rotate page ``index`` 90 degrees clockwise."""
        self._adapter.rotate_page(index, 90)

    # ---- Deletion -------------------------------------------------------------

    def delete_page(self, index: int) -> None:
        """Delete a single page."""
        self._adapter.delete_pages([index])

    def delete_pages(self, indices: Iterable[int]) -> None:
        """Delete a set of pages.

        Indices may be in any order; the adapter sorts and applies in
        reverse so earlier indices remain valid during the operation.
        """
        self._adapter.delete_pages(list(indices))

    # ---- Insertion ------------------------------------------------------------

    def insert_blank_page_after(self, index: int, width: float, height: float) -> None:
        """Insert a blank page right after ``index``."""
        self._adapter.insert_blank_page(index + 1, width, height)

    def insert_blank_page_before(self, index: int, width: float, height: float) -> None:
        """Insert a blank page right before ``index``."""
        self._adapter.insert_blank_page(index, width, height)

    def append_blank_page(self, width: float, height: float) -> None:
        """Append a blank page at the end of the document."""
        self._adapter.insert_blank_page(self._adapter.page_count, width, height)

    # ---- Duplication ----------------------------------------------------------

    def duplicate_page(self, index: int) -> None:
        """Duplicate a page; the copy is inserted right after the original."""
        self._adapter.duplicate_page(index)

    # ---- Move/reorder ---------------------------------------------------------

    def move_page(self, from_index: int, to_index: int) -> None:
        """Move a page; ``to_index`` is the desired post-move position."""
        self._adapter.move_page(from_index, to_index)

    # ---- Crop -----------------------------------------------------------------

    def crop_page(self, index: int, margins: tuple[float, float, float, float]) -> None:
        """Crop a page by ``(top, right, bottom, left)`` margins in PDF points.

        Pass ``(0, 0, 0, 0)`` to clear an existing crop.
        """
        self._adapter.crop_page(index, margins)

    # ---- Cross-document (PR 8.5) ---------------------------------------------
    def extract_to_file(
        self,
        from_index: int,
        to_index: int,
        output_path: Path,
    ) -> None:
        """Save pages ``from_index..to_index`` (inclusive) as a new PDF.

        Source document is left untouched (its dirty flag is not
        affected). Creates a fresh in-memory PDF, copies the page
        range into it, writes it to ``output_path``.
        """
        out = PyMuPDFAdapter()
        try:
            out.new_document()
            out.insert_pdf(self._adapter, from_index, to_index, 0)
            out.save(output_path)
        finally:
            out.close()

    def insert_from(
        self,
        source_path: Path,
        from_index: int,
        to_index: int,
        at_index: int,
    ) -> None:
        """Insert pages from a PDF on disk into the bound document.

        Opens ``source_path`` headlessly, inserts the requested
        range before ``at_index`` of the bound document, closes
        the source. Bound document becomes dirty.
        """
        source = PyMuPDFAdapter()
        try:
            source.open(source_path)
            self._adapter.insert_pdf(source, from_index, to_index, at_index)
        finally:
            source.close()

    def split(
        self,
        breakpoints: list[int],
        output_dir: Path,
        stem: str,
    ) -> list[Path]:
        """Split the document at 0-based ``breakpoints`` into multiple PDFs.

        Each output file contains a contiguous slice of the
        source. ``breakpoints`` are start-of-slice indices (not
        including 0; the first slice always starts at 0).

        Output files are named ``f"{stem}-{N:0Wd}.pdf"`` where N
        is 1-based and W is the digit width of the largest N. The
        list of written paths is returned in slice order.
        """
        page_count = self._adapter.page_count
        if page_count == 0:
            return []
        # Build slice ranges from breakpoints.
        sorted_breaks = sorted({b for b in breakpoints if 0 < b < page_count})
        starts = [0, *sorted_breaks]
        ends = [*sorted_breaks, page_count]  # exclusive ends
        ranges = list(zip(starts, ends, strict=True))
        width = len(str(len(ranges)))
        outputs: list[Path] = []
        for i, (start, end) in enumerate(ranges, start=1):
            out_path = output_dir / f"{stem}-{i:0{width}d}.pdf"
            out = PyMuPDFAdapter()
            try:
                out.new_document()
                out.insert_pdf(self._adapter, start, end - 1, 0)
                out.save(out_path)
            finally:
                out.close()
            outputs.append(out_path)
        return outputs


def merge(
    sources: list[DocumentAdapter],
    output_path: Path,
) -> None:
    """Combine sources in order into a single PDF at ``output_path``.

    Free function (not a ``PageService`` method) because it
    fundamentally operates on multiple adapters, not one bound
    instance. Each source's in-memory state is used as-is,
    including any unsaved mutations; sources are not modified.
    """
    if len(sources) < 2:
        from pdfprism.core.exceptions import PageOperationError

        raise PageOperationError("merge requires at least two sources")
    out = PyMuPDFAdapter()
    try:
        out.new_document()
        for s in sources:
            n = s.page_count
            if n == 0:
                continue
            out.insert_pdf(s, 0, n - 1, out.page_count)
        out.save(output_path)
    finally:
        out.close()
