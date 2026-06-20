"""Type definitions for the pdfprism core layer.

Plain dataclasses with no behavior; meant to be returned by adapters and
consumed by services and UI without coupling them to any PDF library.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageInfo:
    """Lightweight metadata about a single page."""

    index: int
    width_points: float
    height_points: float
    rotation: int


@dataclass(frozen=True)
class DocumentInfo:
    """Document-level metadata."""

    page_count: int
    title: str | None
    author: str | None
    subject: str | None
    keywords: str | None
    creator: str | None
    producer: str | None
    is_encrypted: bool
    needs_password: bool


@dataclass(frozen=True)
class OutlineItem:
    """A single entry in a PDF document outline (table of contents).

    The outline is returned as a flat list with hierarchy expressed through
    ``level``: ``level=1`` is a top-level chapter, ``level=2`` is a child
    of the most recent level-1 entry, and so on. This shape matches PyMuPDF's
    ``Document.get_toc()`` and is what the ``OutlinePanel`` model expects.
    """

    level: int
    title: str
    page_index: int


@dataclass(frozen=True)
class SearchHit:
    """A single match of a search term on a page.

    Coordinates are in PDF page space (1 unit = 1/72 inch, origin top-left),
    matching ``DocumentAdapter.render_page`` coordinates. Consumers that
    overlay highlights on a rendered pixmap scale by their render-zoom
    factor. Equality is structural (frozen dataclass), so tests can compare
    hits directly.
    """

    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class CrossDocHit:
    """A SearchHit tagged with its source document's index in a list of adapters.

    The doc_index refers to the position of the originating adapter in the
    list passed to SearchService.find_all_across. The caller (MainWindow)
    maps that index back to a DocumentView / tab.
    """

    doc_index: int
    hit: SearchHit
