"""PyMuPDF-backed implementation of DocumentAdapter."""

import logging
from pathlib import Path

import pymupdf

from pdfprism.core.exceptions import (
    DocumentOpenError,
    PageOutOfRangeError,
    PasswordRequiredError,
)
from pdfprism.core.types import DocumentInfo, OutlineItem, PageInfo, SearchHit

logger = logging.getLogger(__name__)


class PyMuPDFAdapter:
    """DocumentAdapter implementation using PyMuPDF (a.k.a. fitz)."""

    def __init__(self) -> None:
        self._doc: pymupdf.Document | None = None

    def open(self, path: Path, password: str | None = None) -> None:
        if not path.exists():
            raise DocumentOpenError(f"File not found: {path}")
        try:
            doc = pymupdf.open(str(path))
        except pymupdf.FileDataError as exc:
            raise DocumentOpenError(f"Not a valid PDF: {path}") from exc
        except Exception as exc:
            raise DocumentOpenError(f"Failed to open {path}: {exc}") from exc

        if doc.needs_pass:
            if password is None or not doc.authenticate(password):
                doc.close()
                raise PasswordRequiredError(f"Password required for {path}")

        if self._doc is not None:
            self._doc.close()
        self._doc = doc
        logger.info("Opened document: %s (%d pages)", path, doc.page_count)

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
            logger.info("Closed document")

    @property
    def page_count(self) -> int:
        self._require_open()
        assert self._doc is not None
        return self._doc.page_count

    def get_document_info(self) -> DocumentInfo:
        self._require_open()
        assert self._doc is not None
        meta = self._doc.metadata or {}
        return DocumentInfo(
            page_count=self._doc.page_count,
            title=meta.get("title") or None,
            author=meta.get("author") or None,
            subject=meta.get("subject") or None,
            keywords=meta.get("keywords") or None,
            creator=meta.get("creator") or None,
            producer=meta.get("producer") or None,
            is_encrypted=bool(self._doc.is_encrypted),
            needs_password=bool(self._doc.needs_pass),
        )

    def get_page_info(self, index: int) -> PageInfo:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[index]
        rect = page.rect
        return PageInfo(
            index=index,
            width_points=float(rect.width),
            height_points=float(rect.height),
            rotation=int(page.rotation),
        )

    def render_page(self, index: int, zoom: float = 1.0) -> bytes:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[index]
        matrix = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")

    def get_outline(self) -> list[OutlineItem]:
        self._require_open()
        assert self._doc is not None
        toc = self._doc.get_toc()
        return [
            OutlineItem(
                level=int(entry[0]),
                title=str(entry[1]),
                page_index=max(0, int(entry[2]) - 1),
            )
            for entry in toc
        ]

    def _require_open(self) -> None:
        if self._doc is None:
            raise DocumentOpenError("No document is currently open")

    def search_page(self, index: int, term: str) -> list[SearchHit]:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        if not term:
            return []
        page = self._doc[index]
        rects = page.search_for(term)
        return [
            SearchHit(
                page_index=index,
                x0=float(r.x0),
                y0=float(r.y0),
                x1=float(r.x1),
                y1=float(r.y1),
            )
            for r in rects
        ]
