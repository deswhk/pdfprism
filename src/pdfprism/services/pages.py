"""Page-operation service.

Thin wrapper around the adapter's mutation methods, named after user intent.
Lives at the service layer so:

- UI code stays out of the adapter directly (parallels SearchService/ExtractService).
- Operations are testable without Qt.
- Future composite operations (PR 11 redaction → crop, PR 8.5 cross-doc page
  insertion) have a place to live.

All operations mutate the bound adapter in place and set its dirty flag.
Index validation is delegated to the adapter; see ``DocumentAdapter`` for
the exception contract.
"""

from __future__ import annotations

from collections.abc import Iterable

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
