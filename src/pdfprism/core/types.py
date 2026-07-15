"""Type definitions for the pdfprism core layer.

Plain dataclasses with no behavior; meant to be returned by adapters and
consumed by services and UI without coupling them to any PDF library.
"""

from dataclasses import dataclass

Quad = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]
"""Four corner points (upper-left, upper-right, lower-right, lower-left)."""


@dataclass(frozen=True)
class Word:
    """A single extracted word in PDF page space.

    Coordinates match ``SearchHit`` and ``DocumentAdapter.render_page``
    (1 unit = 1/72 inch, origin top-left). Used by the search service for
    case-sensitive and whole-word matching above the adapter.
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


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
    quad: Quad | None = None


@dataclass(frozen=True)
class CrossDocHit:
    """A SearchHit tagged with its source document's index in a list of adapters.

    The doc_index refers to the position of the originating adapter in the
    list passed to SearchService.find_all_across. The caller (MainWindow)
    maps that index back to a DocumentView / tab.
    """

    doc_index: int
    hit: SearchHit


@dataclass(frozen=True)
class ExtractedImage:
    """A single image extracted from a PDF page."""

    page_index: int
    xref: int
    width: int
    height: int
    ext: str
    data: bytes


@dataclass(frozen=True)
class EncryptionSpec:
    """Save-time encryption spec for PDF documents (PR 10.5).

    Passed to ``DocumentAdapter.save(encryption=...)`` to change the
    encryption state of the output file. ``None`` on the ``encryption``
    argument means "preserve current state" (the pre-PR-10.5 default);
    passing an explicit spec is how a caller opts into a change.

    Value semantics:
        - ``user_password=None`` and ``owner_password=None`` -> output
          has no encryption at all. This is the "remove password" case.
        - ``user_password="foo"`` and ``owner_password=None`` ->
          owner_password defaults to the user_password. PyMuPDF requires
          *some* owner password when a user password is set; using the
          same string is the standard convention when the caller only
          cares about read access control.
        - ``user_password="foo"`` and ``owner_password="bar"`` -> both
          set as given. PR 10.5 does not surface this in the dialog
          (owner-password-driven permission changes are PR 11); the
          field is exposed for future callers and testability.
        - ``user_password=None`` and ``owner_password="bar"`` -> invalid.
          The adapter rejects this case; owner-only encryption without
          user access control is a nonsense combination for pdfprism.

    ``algorithm`` is currently hard-coded to ``"AES-256"`` (PDF 2.0
    standard). RC4 variants and AES-128 are supported by PyMuPDF but
    not exposed in PR 10.5 -- AES-256 is the sole modern-safe default.
    Field kept on the spec for future extensibility (algorithm picker
    in the dialog would surface here first).
    """

    user_password: str | None
    owner_password: str | None = None
    algorithm: str = "AES-256"
