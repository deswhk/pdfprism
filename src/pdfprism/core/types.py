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
