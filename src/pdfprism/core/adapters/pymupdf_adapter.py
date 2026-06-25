"""PyMuPDF-backed implementation of DocumentAdapter."""

import logging
from pathlib import Path

import pymupdf

from pdfprism.core.exceptions import (
    DocumentOpenError,
    DocumentSaveError,
    PageOperationError,
    PageOutOfRangeError,
    PasswordRequiredError,
)
from pdfprism.core.types import DocumentInfo, ExtractedImage, OutlineItem, PageInfo, SearchHit, Word

logger = logging.getLogger(__name__)


class PyMuPDFAdapter:
    """DocumentAdapter implementation using PyMuPDF (a.k.a. fitz)."""

    def __init__(self) -> None:
        self._doc: pymupdf.Document | None = None
        self._path: Path | None = None
        self._is_dirty: bool = False

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
        self._path = path
        self._is_dirty = False
        logger.info("Opened document: %s (%d pages)", path, doc.page_count)

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
            logger.info("Closed document")
        self._path = None
        self._is_dirty = False

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
        # quads=True returns proper quadrilaterals for rotated pages, so the
        # highlight overlay can follow the text orientation. The bounding box
        # (x0/y0/x1/y1) is derived from the four corners and equals the
        # legacy rect on rotation-0 pages. quad is left None when rotation is
        # 0 (axis-aligned, redundant with rect) so consumers can use it as a
        # cheap signal of 'render as polygon'.
        rotation = int(page.rotation)
        # search_for returns quads in *unrotated* PDF page space. The
        # rendered pixmap is in layout (rotated) space, so on rotated pages
        # we project quads through page.rotation_matrix to align overlays
        # with the displayed text. Empirically (PyMuPDF 1.26) it is
        # rotation_matrix that maps unrotated -> layout; derotation_matrix
        # goes the other way despite the docstring wording.
        quads = page.search_for(term, quads=True)
        if rotation != 0:
            matrix = page.rotation_matrix
            quads = [q * matrix for q in quads]
        hits: list[SearchHit] = []
        for q in quads:
            xs = (q.ul.x, q.ur.x, q.lr.x, q.ll.x)
            ys = (q.ul.y, q.ur.y, q.lr.y, q.ll.y)
            quad = None
            if rotation != 0:
                quad = (
                    (float(q.ul.x), float(q.ul.y)),
                    (float(q.ur.x), float(q.ur.y)),
                    (float(q.lr.x), float(q.lr.y)),
                    (float(q.ll.x), float(q.ll.y)),
                )
            hits.append(
                SearchHit(
                    page_index=index,
                    x0=float(min(xs)),
                    y0=float(min(ys)),
                    x1=float(max(xs)),
                    y1=float(max(ys)),
                    quad=quad,
                )
            )
        return hits

    def extract_words(self, index: int) -> list[Word]:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[index]
        rotation = int(page.rotation)
        raw = page.get_text("words")
        if rotation == 0:
            return [
                Word(
                    text=str(w[4]),
                    x0=float(w[0]),
                    y0=float(w[1]),
                    x1=float(w[2]),
                    y1=float(w[3]),
                )
                for w in raw
            ]
        # Project each word rect into layout space so the slow-path
        # (case-sensitive / whole-word) hits land on the rendered glyphs.
        # The transformed Rect is still axis-aligned for 90/180/270 rotations.
        matrix = page.rotation_matrix
        words: list[Word] = []
        for w in raw:
            r = pymupdf.Rect(w[0], w[1], w[2], w[3]) * matrix
            words.append(
                Word(
                    text=str(w[4]),
                    x0=float(min(r.x0, r.x1)),
                    y0=float(min(r.y0, r.y1)),
                    x1=float(max(r.x0, r.x1)),
                    y1=float(max(r.y0, r.y1)),
                )
            )
        return words

    def extract_text(self, index: int) -> str:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[index]
        return str(page.get_text("text"))

    def extract_images(self, index: int) -> list[ExtractedImage]:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[index]
        images: list[ExtractedImage] = []
        for img_info in page.get_images(full=True):
            xref = int(img_info[0])
            try:
                data = self._doc.extract_image(xref)
            except Exception:
                continue
            images.append(
                ExtractedImage(
                    page_index=index,
                    xref=xref,
                    width=int(data["width"]),
                    height=int(data["height"]),
                    ext=str(data["ext"]),
                    data=bytes(data["image"]),
                )
            )
        return images

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    def rotate_page(self, index: int, degrees: int) -> None:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        if degrees not in (90, 180, 270):
            raise PageOperationError(f"Rotation must be 90, 180, or 270; got {degrees}")
        page = self._doc[index]
        page.set_rotation((page.rotation + degrees) % 360)
        self._is_dirty = True

    def delete_pages(self, indices: list[int]) -> None:
        self._require_open()
        assert self._doc is not None
        unique = sorted(set(indices))
        if not unique:
            return
        for i in unique:
            if not 0 <= i < self._doc.page_count:
                raise PageOutOfRangeError(
                    f"Page index {i} out of range [0, {self._doc.page_count})"
                )
        if len(unique) >= self._doc.page_count:
            raise PageOperationError("Cannot delete every page; document would be empty")
        for i in reversed(unique):
            self._doc.delete_page(i)
        self._is_dirty = True

    def insert_blank_page(self, index: int, width: float, height: float) -> None:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index <= self._doc.page_count:
            raise PageOutOfRangeError(
                f"Insert index {index} out of range [0, {self._doc.page_count}]"
            )
        if width <= 0 or height <= 0:
            raise PageOperationError(f"Page dimensions must be positive; got {width}x{height}")
        self._doc.new_page(pno=index, width=width, height=height)
        self._is_dirty = True

    def duplicate_page(self, index: int) -> None:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        # PyMuPDF's fullcopy_page copies the source page to a destination
        # index; passing the source index + 1 inserts the copy right after.
        self._doc.fullcopy_page(index, index + 1)
        self._is_dirty = True

    def move_page(self, from_index: int, to_index: int) -> None:
        self._require_open()
        assert self._doc is not None
        n = self._doc.page_count
        if not 0 <= from_index < n:
            raise PageOutOfRangeError(f"From index {from_index} out of range [0, {n})")
        if not 0 <= to_index < n:
            raise PageOutOfRangeError(f"To index {to_index} out of range [0, {n})")
        if from_index == to_index:
            return
        # PyMuPDF's Document.move_page(pno, to) semantics, verified
        # empirically against pymupdf 1.27:
        #   - to is the *original-coordinate* index to insert before
        #   - to=-1 means move to the very end
        #   - move_page(0, 2) on [P0,P1,P2,P3] -> [P1,P0,P2,P3]
        #     (so post-removal index 1, not 2)
        #   - move_page(3, 0) on [P0,P1,P2,P3] -> [P3,P0,P1,P2]
        #     (so post-removal index 0 directly)
        # Our contract: to_index is the desired post-removal index.
        # Backward move: pass to_index directly.
        # Forward move to last index: use -1 sentinel.
        # Forward move to middle: pass to_index + 1.
        if from_index > to_index:
            self._doc.move_page(from_index, to_index)
        elif to_index == n - 1:
            self._doc.move_page(from_index, -1)
        else:
            self._doc.move_page(from_index, to_index + 1)
        self._is_dirty = True

    def crop_page(
        self,
        index: int,
        margins: tuple[float, float, float, float],
    ) -> None:
        self._require_open()
        assert self._doc is not None
        if not 0 <= index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {index} out of range [0, {self._doc.page_count})"
            )
        top, right, bottom, left = margins
        if any(m < 0 for m in margins):
            raise PageOperationError(f"Crop margins must be non-negative; got {margins}")
        page = self._doc[index]
        mb = page.mediabox
        new_rect = pymupdf.Rect(
            mb.x0 + left,
            mb.y0 + top,
            mb.x1 - right,
            mb.y1 - bottom,
        )
        if new_rect.width <= 0 or new_rect.height <= 0:
            raise PageOperationError(f"Crop margins {margins} leave zero or negative area")
        page.set_cropbox(new_rect)
        self._is_dirty = True

    def save(self, path: Path | None = None) -> None:
        self._require_open()
        assert self._doc is not None
        target = path if path is not None else self._path
        if target is None:
            raise DocumentSaveError("Cannot save: no destination path")
        try:
            # incremental=False forces a full rewrite. For in-place save
            # over the same path PyMuPDF requires incremental=True OR a
            # temp-file dance; we use the temp-file dance because some
            # operations (delete, insert) are incompatible with incremental.
            if target == self._path:
                tmp = target.with_suffix(target.suffix + ".pdfprism-tmp")
                self._doc.save(str(tmp))
                # Close the open document before swapping the file
                # because Windows may hold the file lock.
                self._doc.close()
                self._doc = None
                tmp.replace(target)
                # Re-open the saved document so the adapter stays usable.
                self._doc = pymupdf.open(str(target))
            else:
                self._doc.save(str(target))
                self._path = target
        except (OSError, RuntimeError) as exc:
            raise DocumentSaveError(f"Save failed: {exc}") from exc
        self._is_dirty = False
