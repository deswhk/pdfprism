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
from pdfprism.core.types import (
    DocumentInfo,
    EncryptionSpec,
    ExtractedImage,
    OutlineItem,
    PageInfo,
    Redaction,
    RedactionGroup,
    SearchHit,
    Word,
)

logger = logging.getLogger(__name__)


class PyMuPDFAdapter:
    """DocumentAdapter implementation using PyMuPDF (a.k.a. fitz)."""

    def __init__(self) -> None:
        self._doc: pymupdf.Document | None = None
        self._path: Path | None = None
        self._is_dirty: bool = False
        # PR 10.5: password the current doc was authenticated with,
        # if encrypted. None for unencrypted docs.
        self._current_password: str | None = None
        # PR 10.5: pre-auth snapshot of doc.needs_pass; used throughout
        # the adapter instead of live doc.needs_pass reads. Reading
        # doc.needs_pass on an authenticated encrypted doc in PyMuPDF
        # 1.27.x de-authenticates it silently -- see open() docstring.
        self._is_encrypted_at_open: bool = False

    def open(self, path: Path, password: str | None = None) -> None:
        if not path.exists():
            raise DocumentOpenError(f"File not found: {path}")
        try:
            doc = pymupdf.open(str(path))
        except pymupdf.FileDataError as exc:
            raise DocumentOpenError(f"Not a valid PDF: {path}") from exc
        except Exception as exc:
            raise DocumentOpenError(f"Failed to open {path}: {exc}") from exc

        was_encrypted = bool(doc.needs_pass)
        if was_encrypted:
            if password is None or not doc.authenticate(password):
                doc.close()
                raise PasswordRequiredError(f"Password required for {path}")

        if self._doc is not None:
            self._doc.close()
        self._doc = doc
        self._path = path
        self._is_dirty = False
        # PR 10.5: remember the password so save(encryption=None)
        # can preserve encryption on an encrypted doc. PyMuPDF's
        # bare save() default is to STRIP encryption, which would
        # be a data-security regression from the user's perspective.
        self._current_password = password if was_encrypted else None
        self._is_encrypted_at_open = was_encrypted
        page_count = doc.page_count
        logger.info("Opened document: %s (%d pages)", path, page_count)

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
            logger.info("Closed document")
        self._is_encrypted_at_open = False
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
            needs_password=self._is_encrypted_at_open,
        )

    # ---- PR 11: metadata + permissions --------------------------------

    _METADATA_FIELDS = (
        "title",
        "author",
        "subject",
        "keywords",
        "creator",
        "producer",
    )

    def get_metadata(self) -> dict[str, str | None]:
        """Return the six standard PDF Info dict fields.

        Keys: title, author, subject, keywords, creator, producer.
        Empty strings from PyMuPDF are normalised to ``None`` so
        callers see a consistent 'missing' representation.
        """
        self._require_open()
        assert self._doc is not None
        meta = self._doc.metadata or {}
        return {field: (meta.get(field) or None) for field in self._METADATA_FIELDS}

    def set_metadata(self, updates: dict[str, str | None]) -> None:
        """Update selected Info dict fields.

        Only keys present in ``updates`` are changed; others are
        preserved. Passing ``None`` for a value clears that field.
        Unknown keys are ignored (defensive against future PDF spec
        additions). Marks the document dirty.
        """
        self._require_open()
        assert self._doc is not None
        current = dict(self._doc.metadata or {})
        for key, value in updates.items():
            if key not in self._METADATA_FIELDS:
                continue
            current[key] = value if value is not None else ""
        self._doc.set_metadata(current)
        self._is_dirty = True

    def delete_xml_metadata(self) -> None:
        """Remove the XMP metadata stream from the document.

        XMP is the PDF 2.0 metadata channel. Info-dict clearing
        alone leaves XMP intact -- provenance/authorship info can
        survive a metadata sanitize if this isn't also called.
        No-op if the doc has no XMP stream. Marks the document
        dirty.
        """
        self._require_open()
        assert self._doc is not None
        try:
            self._doc.del_xml_metadata()
        except Exception:
            # PyMuPDF raises on missing XMP in some versions; treat as no-op.
            pass
        self._is_dirty = True

    # ---- PR 12: redactions --------------------------------------------

    def add_redaction(self, redaction: Redaction) -> None:
        """Add a pending redaction annotation to the document.

        Redactions are two-phase: this method creates an annotation
        (still reversible via ``remove_redaction`` or by not calling
        ``apply_redactions``). Actual destruction of the underlying
        content only happens on ``apply_redactions()``.

        Args:
            redaction: The Redaction to add. ``rect`` is in PDF-space
                coordinates (points); ``fill_color`` is RGB 0-255
                (converted internally to PyMuPDF's 0-1 float triple).

        Marks the document dirty.
        """
        self._require_open()
        assert self._doc is not None
        if not 0 <= redaction.page_index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {redaction.page_index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[redaction.page_index]
        rect = pymupdf.Rect(*redaction.rect)
        # PyMuPDF fill: (r, g, b) as floats 0-1
        fill = tuple(c / 255.0 for c in redaction.fill_color)
        kwargs: dict = {"fill": fill, "cross_out": True}
        if redaction.replacement_text is not None:
            kwargs["text"] = redaction.replacement_text
        annot = page.add_redact_annot(rect, **kwargs)
        # PR 14a workaround for PyMuPDF gap: the ``text=`` kwarg is used at
        # apply time but does not round-trip via ``annot.info``. Mirror the
        # replacement text into ``info["content"]`` so ``list_redactions``
        # can read it back correctly.
        if redaction.replacement_text is not None:
            info = annot.info
            info["content"] = redaction.replacement_text
            annot.set_info(info)
            annot.update()
        self._is_dirty = True

    def add_redactions_for_words(
        self,
        page_index: int,
        words: list["Word"],
        *,
        fill_color: tuple[int, int, int] = (0, 0, 0),
        replacement_text: str | None = None,
    ) -> int:
        """PR 12.1: create one redaction annotation per Word.

        Used by the text-selection redaction path -- user selects text
        via SELECT mode, right-clicks, chooses "Redact Selection".
        Each selected Word gets its own redact_annot with the word's
        rect. Per-word rects (rather than a union rect) avoid
        redacting whitespace between multi-line selections and unrelated
        content in multi-column layouts.

        Args:
            page_index: Page these words belong to.
            words: Word objects from the current selection. Empty list
                is a no-op returning 0.

        Returns:
            Count of redactions added (== len(words)).

        Marks the document dirty when at least one redaction is added.
        """
        self._require_open()
        assert self._doc is not None
        if not words:
            return 0
        if not 0 <= page_index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {page_index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[page_index]
        for word in words:
            rect = pymupdf.Rect(word.x0, word.y0, word.x1, word.y1)
            fill = tuple(c / 255.0 for c in fill_color)
            kwargs: dict = {"fill": fill, "cross_out": True}
            if replacement_text is not None:
                kwargs["text"] = replacement_text
            annot = page.add_redact_annot(rect, **kwargs)
            # PR 14a: mirror text into info.content for round-trip
            if replacement_text is not None:
                info = annot.info
                info["content"] = replacement_text
                annot.set_info(info)
                annot.update()
        self._is_dirty = True
        return len(words)

    def add_redactions_for_hits(
        self,
        hits: list["SearchHit"],
        *,
        fill_color: tuple[int, int, int] = (0, 0, 0),
        replacement_text: str | None = None,
    ) -> int:
        """PR 12.2: create one redaction annotation per SearchHit.

        Used by the search-then-redact path -- user types a term into
        the SearchRedactDialog, picks matches, and commits them as
        pending redactions. SearchHits already carry ``page_index``
        and ``(x0, y0, x1, y1)`` in PDF-space, so the batch API just
        loops per-page for efficiency (one page load per page, not
        per hit).

        Args:
            hits: SearchHit objects to redact. Empty list is a no-op
                returning 0.

        Returns:
            Count of redactions added (== len(hits)).

        Marks the document dirty when at least one redaction is added.
        Raises PageOutOfRangeError if any hit references an invalid
        page (defensive; shouldn't happen from a legitimate search).
        """
        self._require_open()
        assert self._doc is not None
        if not hits:
            return 0
        # Group by page for efficiency.
        by_page: dict[int, list[SearchHit]] = {}
        for hit in hits:
            if not 0 <= hit.page_index < self._doc.page_count:
                raise PageOutOfRangeError(
                    f"Hit references page {hit.page_index} out of range [0, {self._doc.page_count})"
                )
            by_page.setdefault(hit.page_index, []).append(hit)
        for page_index, page_hits in by_page.items():
            page = self._doc[page_index]
            fill = tuple(c / 255.0 for c in fill_color)
            for hit in page_hits:
                rect = pymupdf.Rect(hit.x0, hit.y0, hit.x1, hit.y1)
                kwargs: dict = {"fill": fill, "cross_out": True}
                if replacement_text is not None:
                    kwargs["text"] = replacement_text
                annot = page.add_redact_annot(rect, **kwargs)
                # PR 14a: mirror text into info.content for round-trip
                if replacement_text is not None:
                    info = annot.info
                    info["content"] = replacement_text
                    annot.set_info(info)
                    annot.update()
        self._is_dirty = True
        return len(hits)

    def list_redactions(self) -> list[Redaction]:
        """Return all pending redaction annotations in page-major order.

        Walks every page, collects PDF_ANNOT_REDACT annotations, and
        returns them as ``Redaction`` objects. Applied redactions
        (where ``apply_redactions()`` has been called) do NOT appear
        here -- once applied, the annotation is consumed and only the
        destructive change remains.
        """
        self._require_open()
        assert self._doc is not None
        result: list[Redaction] = []
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                rect = annot.rect
                # PyMuPDF fill: 0-1 floats; convert back to 0-255 RGB.
                info = annot.info
                # Some annotations may have no fill color; default to black.
                fill_color = (0, 0, 0)
                if annot.colors and annot.colors.get("fill"):
                    fill = annot.colors["fill"]
                    fill_color = tuple(int(round(c * 255)) for c in fill)
                # Replacement text lives in annot.info["content"] (if set).
                replacement_text = info.get("content") or None
                result.append(
                    Redaction(
                        page_index=page_index,
                        rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                        replacement_text=replacement_text,
                        fill_color=fill_color,
                    )
                )
        return result

    def get_text_in_rect(self, page_index: int, rect: tuple[float, float, float, float]) -> str:
        """PR 14a: extract text within a rectangle on a page.

        Uses PyMuPDF's ``page.get_textbox`` to pull text spanning the
        given rectangle. Returns empty string when the region contains
        no extractable text (image regions, blank areas). Whitespace
        is preserved as-is; normalization for grouping happens in
        ``_normalize_group_text`` when building groups.
        """
        self._require_open()
        assert self._doc is not None
        if not (0 <= page_index < self._doc.page_count):
            raise PageOutOfRangeError(page_index, self._doc.page_count)
        page = self._doc[page_index]
        rect_obj = pymupdf.Rect(*rect)
        text = page.get_textbox(rect_obj) or ""
        return str(text)

    @staticmethod
    def _normalize_group_text(text: str) -> str:
        """PR 14a: normalize extracted text for group key equivalence.

        Case-insensitive + whitespace-collapsed. Empty strings pass
        through unchanged so they can be distinguished from real text.
        """
        if not text:
            return ""
        return " ".join(text.split()).lower()

    def list_redactions_grouped(
        self,
        session_fill: tuple[int, int, int] = (0, 0, 0),
        session_text: str | None = None,
    ) -> list["RedactionGroup"]:
        """PR 14a: return pending redactions grouped by normalized text.

        Groups pending marks by their normalized extracted text (from
        ``get_text_in_rect`` + ``_normalize_group_text``). Marks with
        empty extracted text (image regions, whitespace-only) become
        singleton groups keyed by ``__region__:page:page_index``.

        ``is_customized`` per group is computed by comparing the first
        mark's fill/text to the supplied session defaults. All marks
        in a group share styling by design (group-atomic principle),
        so the first mark's values are representative.

        Groups are ordered by first-appearance page/rect for stable
        listing in the UI.
        """
        self._require_open()
        # Group by (normalized_text_key, display_text). Preserve first-seen
        # display text for the group label (matches how humans think about
        # the entity: the capitalization they typed).
        groups_map: dict[str, dict] = {}
        insertion_order: list[str] = []

        for redaction in self.list_redactions():
            raw_text = self.get_text_in_rect(redaction.page_index, redaction.rect)
            normalized = self._normalize_group_text(raw_text)

            if not normalized:
                # Region-based mark: singleton group per mark
                key = f"__region__:page:{redaction.page_index}:{redaction.rect}"
                display = f"(image region, page {redaction.page_index + 1})"
            else:
                key = normalized
                display = raw_text.strip()

            if key not in groups_map:
                groups_map[key] = {"display": display, "marks": []}
                insertion_order.append(key)
            groups_map[key]["marks"].append(redaction)

        result: list[RedactionGroup] = []
        for key in insertion_order:
            entry = groups_map[key]
            marks = entry["marks"]
            # is_customized: any mark differing from session defaults means
            # customized. Per group-atomic principle, all marks in a group
            # should have the same styling; take the first as representative.
            first = marks[0]
            is_customized = (
                first.fill_color != session_fill or first.replacement_text != session_text
            )
            result.append(
                RedactionGroup(
                    text=entry["display"],
                    normalized_text=key,
                    marks=marks,
                    is_customized=is_customized,
                )
            )
        return result

    def update_redaction_group(
        self,
        text_query: str,
        fill_color: tuple[int, int, int],
        replacement_text: str | None,
    ) -> int:
        """PR 14a: update fill/text on all marks in a group.

        Groups are keyed by normalized extracted text. ``text_query``
        should be either the normalized_text of a real text group or a
        synthetic ``__region__:page:N:...`` key for singleton region
        groups. Iterates pending redaction annotations, updates each
        matching mark's fill and replacement text. Returns the count
        of marks updated.

        Group atomicity: all marks in a group share styling. Callers
        pass a single (fill, text) tuple; every mark in the group
        adopts these values uniformly.
        """
        self._require_open()
        assert self._doc is not None
        updated = 0
        # PyMuPDF color: 0-1 floats
        fill_float = tuple(c / 255.0 for c in fill_color)
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            to_recreate: list[tuple[float, float, float, float]] = []
            for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                raw = self.get_text_in_rect(
                    page_index,
                    (annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1),
                )
                normalized = self._normalize_group_text(raw)
                if normalized:
                    if normalized != text_query:
                        continue
                else:
                    rect_tuple = (
                        annot.rect.x0,
                        annot.rect.y0,
                        annot.rect.x1,
                        annot.rect.y1,
                    )
                    expected_key = f"__region__:page:{page_index}:{rect_tuple}"
                    if text_query != expected_key:
                        continue
                to_recreate.append((annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1))
            for annot in list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
                rect_tuple = (annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1)
                if rect_tuple in to_recreate:
                    page.delete_annot(annot)
            for rect_tuple in to_recreate:
                rect = pymupdf.Rect(*rect_tuple)
                kwargs: dict = {"fill": fill_float, "cross_out": True}
                if replacement_text is not None:
                    kwargs["text"] = replacement_text
                new_annot = page.add_redact_annot(rect, **kwargs)
                if replacement_text is not None:
                    info = new_annot.info
                    info["content"] = replacement_text
                    new_annot.set_info(info)
                    new_annot.update()
                updated += 1
        if updated > 0:
            self._is_dirty = True
        return updated

    def remove_redaction_group(self, text_query: str) -> int:
        """PR 14a: delete all pending marks in a group matching text_query.

        Same grouping semantics as ``update_redaction_group``. Returns
        the count of marks removed.
        """
        self._require_open()
        assert self._doc is not None
        removed = 0
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            # Collect matching annotations first, then delete
            # (mutating during iteration is unsafe with PyMuPDF).
            to_delete: list = []
            for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                raw = self.get_text_in_rect(
                    page_index,
                    (annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1),
                )
                normalized = self._normalize_group_text(raw)
                if normalized:
                    if normalized != text_query:
                        continue
                else:
                    rect_tuple = (
                        annot.rect.x0,
                        annot.rect.y0,
                        annot.rect.x1,
                        annot.rect.y1,
                    )
                    expected_key = f"__region__:page:{page_index}:{rect_tuple}"
                    if text_query != expected_key:
                        continue
                to_delete.append(annot)
            for annot in to_delete:
                page.delete_annot(annot)
                removed += 1
        if removed > 0:
            self._is_dirty = True
        return removed

    def update_pending_matching_defaults(
        self,
        current_defaults: tuple[tuple[int, int, int], str | None],
        new_defaults: tuple[tuple[int, int, int], str | None],
    ) -> int:
        """PR 14a: restyle marks whose fill+text match current defaults.

        Used by the Options-change hook: when session defaults change
        from ``current_defaults`` to ``new_defaults``, marks whose fill
        and text match the OLD defaults are treated as Global marks and
        get their fill/text updated to the NEW defaults. Marks with
        different fill/text (Custom marks) are left untouched.

        This preserves the group-atomic principle: all marks in a
        Global group share styling; all in a Custom group share their
        own styling; Options changes touch only the Global set.

        Returns the count of marks updated.
        """
        self._require_open()
        assert self._doc is not None
        current_fill, current_text = current_defaults
        new_fill, new_text = new_defaults
        updated = 0
        new_fill_float = tuple(c / 255.0 for c in new_fill)
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            # Collect matching annotations first (delete+recreate cannot happen
            # while iterating live annots without invalidation).
            to_recreate: list[tuple[tuple[float, float, float, float], ...]] = []
            for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                annot_fill = (0, 0, 0)
                if annot.colors and annot.colors.get("fill"):
                    fill = annot.colors["fill"]
                    annot_fill = tuple(int(round(c * 255)) for c in fill)
                annot_text = annot.info.get("content") or None
                if annot_fill != current_fill:
                    continue
                if annot_text != current_text:
                    continue
                to_recreate.append((annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1))
            # Delete all matching annots, then re-add with new values. Delete
            # phase and recreate phase are separated so the iterator in the
            # collect phase doesn't become invalidated.
            for annot in list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
                rect_tuple = (annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1)
                if rect_tuple in to_recreate:
                    page.delete_annot(annot)
            for rect_tuple in to_recreate:
                rect = pymupdf.Rect(*rect_tuple)
                kwargs: dict = {"fill": new_fill_float, "cross_out": True}
                if new_text is not None:
                    kwargs["text"] = new_text
                new_annot = page.add_redact_annot(rect, **kwargs)
                # Mirror text into info.content for round-trip readability.
                if new_text is not None:
                    info = new_annot.info
                    info["content"] = new_text
                    new_annot.set_info(info)
                    new_annot.update()
                updated += 1
        if updated > 0:
            self._is_dirty = True
        return updated

    def remove_redaction(self, page_index: int, redaction_index: int) -> None:
        """Delete a pending redaction annotation.

        Args:
            page_index: The page containing the redaction.
            redaction_index: 0-based index among the redactions on that
                page (in the order returned by ``list_redactions()``
                filtered to that page).

        Raises:
            PageOutOfRangeError: page_index invalid
            IndexError: redaction_index out of range for the page
        """
        self._require_open()
        assert self._doc is not None
        if not 0 <= page_index < self._doc.page_count:
            raise PageOutOfRangeError(
                f"Page index {page_index} out of range [0, {self._doc.page_count})"
            )
        page = self._doc[page_index]
        redactions = list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))
        if not 0 <= redaction_index < len(redactions):
            raise IndexError(
                f"Redaction index {redaction_index} out of range "
                f"[0, {len(redactions)}) for page {page_index}"
            )
        page.delete_annot(redactions[redaction_index])
        self._is_dirty = True

    def apply_redactions(
        self,
        *,
        images: int = 2,
        graphics: int = 1,
        text: int = 0,
    ) -> int:
        """Destructively apply all pending redactions in the document.

        Iterates over every page and calls PyMuPDF's ``apply_redactions()``.
        The three keyword arguments are passed through to PyMuPDF and
        control how content intersecting the redaction rects is handled:

        Args:
            images: 0=leave alone, 1=blank-fill intersecting images,
                2=fully redact. PyMuPDF default: 2.
            graphics: 0=leave alone, 1=redact intersecting graphics.
                PyMuPDF default: 1.
            text: 0=only redact text within the redaction quad,
                1=also remove any text sharing a line with the quad.
                PyMuPDF default: 0.

        Returns the count of applied redactions. Marks the document
        dirty. After this call, ``list_redactions()`` returns an empty
        list -- the annotations are consumed by the destructive apply.
        """
        self._require_open()
        assert self._doc is not None
        count = 0
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            # Count before apply (apply_redactions() removes the annots).
            page_count = sum(1 for _ in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))
            if page_count == 0:
                continue
            page.apply_redactions(images=images, graphics=graphics, text=text)
            count += page_count
        if count > 0:
            self._is_dirty = True
        return count

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
        if index == self._doc.page_count - 1:
            # PyMuPDF rejects fullcopy_page(N, N+1) when N+1 == page_count;
            # use -1 to append the copy at the end (semantically identical
            # to inserting after the last page).
            self._doc.fullcopy_page(index, -1)
        else:
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

    def save(
        self,
        path: Path | None = None,
        encryption: EncryptionSpec | None = None,
    ) -> None:
        """Save the document.

        Args:
            path: destination. ``None`` saves in-place over the
                path the document was opened from.
            encryption: PR 10.5. ``None`` preserves the current
                encryption state (PyMuPDF default). Pass an
                explicit ``EncryptionSpec`` to change encryption
                on the output file: set/change a password, or
                remove one. See ``EncryptionSpec`` docstring for
                the four valid combinations of user/owner
                password fields.

        Raises:
            DocumentSaveError: on any I/O or PyMuPDF failure, or
                on an invalid ``EncryptionSpec`` (owner-only
                encryption without a user password is rejected).
        """
        self._require_open()
        assert self._doc is not None
        target = path if path is not None else self._path
        if target is None:
            raise DocumentSaveError("Cannot save: no destination path")

        # Resolve encryption kwargs before touching disk so an
        # invalid spec fails fast (no temp file left behind).
        save_kwargs = self._encryption_save_kwargs(encryption)

        try:
            # incremental=False forces a full rewrite. For in-place save
            # over the same path PyMuPDF requires incremental=True OR a
            # temp-file dance; we use the temp-file dance because some
            # operations (delete, insert) are incompatible with incremental.
            if target == self._path:
                tmp = target.with_suffix(target.suffix + ".pdfprism-tmp")
                self._doc.save(str(tmp), **save_kwargs)
                # Close the open document before swapping the file
                # because Windows may hold the file lock.
                self._doc.close()
                self._doc = None
                tmp.replace(target)
                # Re-open the saved document. If we just wrote an
                # encrypted output the caller (service layer) is
                # responsible for authenticating; the adapter leaves
                # it locked so any subsequent operation raises
                # DocumentOpenError until authenticate() is called.
                self._doc = pymupdf.open(str(target))
                # PR 10.5: snapshot needs_pass BEFORE authenticate (see open() note).
                reopened_needs_pass = bool(self._doc.needs_pass)
                if reopened_needs_pass:
                    # PR 10.5: refresh _current_password after encryption change.
                    # If the caller supplied a new spec, use its password;
                    # if this was a preserve save, _current_password is
                    # already correct.
                    if encryption is not None:
                        self._current_password = encryption.user_password or ""
                    self._doc.authenticate(self._current_password or "")
                    # PR 10.5: reflect the post-save encryption state in our snapshot.
                    self._is_encrypted_at_open = True
                elif encryption is not None and encryption.user_password is None:
                    # Encryption was just removed. Clear the stored password.
                    self._current_password = None
                    self._is_encrypted_at_open = False
            else:
                self._doc.save(str(target), **save_kwargs)
                self._path = target
        except (OSError, RuntimeError) as exc:
            raise DocumentSaveError(f"Save failed: {exc}") from exc
        self._is_dirty = False

    def save_compressed(
        self,
        output_path: Path,
        *,
        jpeg_quality: int = 75,
        image_dpi: int = 150,
        recompress_images: bool = True,
        subset_fonts: bool = True,
        garbage_collect: bool = True,
        progress_callback=None,
    ) -> tuple[int, int]:
        """PR 15: save a compressed copy of the document.

        Compression is applied through a combination of:
        - Font subsetting (``subset_fonts``): keep only glyphs
          actually used in the document; typically 30-70% font
          size reduction on docs with large embedded fonts.
        - Object cleanup (``garbage_collect``): PyMuPDF garbage=4
          removes unused objects and compresses object streams.
        - Deflate compression on streams (always applied):
          equivalent to zlib re-compression of content streams.
        - Image recompression (``recompress_images``): rasterize
          embedded images at ``image_dpi`` and re-encode as JPEG
          at ``jpeg_quality``. Sub-step 3 populates this pathway;
          this sub-step is a no-op stub for it.

        Encryption is preserved on the output using the same
        password as the source document (matches the semantics of
        ``save`` with no explicit ``EncryptionSpec``).

        The output always goes to a new path -- there is no
        in-place semantic; users are expected to pick a fresh
        destination via a Save As dialog.

        Args:
            output_path: destination file path.
            jpeg_quality: 1-100. Used when recompress_images=True.
            image_dpi: target DPI for image downsampling. Used
                when recompress_images=True.
            recompress_images: enable image rasterize + re-encode
                pipeline. Sub-step 3 makes this effective; sub-
                step 2 leaves it as a no-op.
            subset_fonts: subset embedded fonts to used glyphs only.
            garbage_collect: apply PyMuPDF garbage=4 cleanup.
            progress_callback: optional ``callable(current, total)``
                for progress reporting during image recompression.

        Returns:
            (original_size_bytes, compressed_size_bytes) tuple.
            Original size is measured from the current source path;
            compressed size is measured from the freshly written
            output_path.

        Raises:
            DocumentSaveError: on any I/O or PyMuPDF failure.
        """
        self._require_open()
        assert self._doc is not None
        if self._path is None:
            raise DocumentSaveError(
                "Cannot compress: source path unknown (document not opened from disk)"
            )
        try:
            original_size = self._path.stat().st_size
        except OSError as exc:
            raise DocumentSaveError(f"Cannot stat source: {exc}") from exc

        # PR 15 sub-step 3 will populate this pathway.
        if recompress_images:
            self._recompress_embedded_images(
                jpeg_quality=jpeg_quality,
                image_dpi=image_dpi,
                progress_callback=progress_callback,
            )

        # Font subsetting: harmless best-effort. PyMuPDF returns silently
        # if no fonts can be subset. We log rather than raise.
        if subset_fonts:
            try:
                self._doc.subset_fonts()
            except Exception as exc:
                logger.info("Font subsetting skipped: %s", exc)

        # PR 10.5: preserve encryption on compressed output.
        save_kwargs = self._encryption_save_kwargs(None)
        if garbage_collect:
            save_kwargs["garbage"] = 4
        save_kwargs["deflate"] = True
        save_kwargs["deflate_images"] = True
        save_kwargs["deflate_fonts"] = True
        save_kwargs["clean"] = True

        try:
            self._doc.save(str(output_path), **save_kwargs)
        except (OSError, RuntimeError) as exc:
            raise DocumentSaveError(f"Compressed save failed: {exc}") from exc

        try:
            compressed_size = output_path.stat().st_size
        except OSError as exc:
            raise DocumentSaveError(f"Compressed file written but cannot stat: {exc}") from exc
        logger.info(
            "Compressed %s -> %s: %d bytes -> %d bytes (%.1f%% reduction)",
            self._path.name,
            output_path.name,
            original_size,
            compressed_size,
            100.0 * (1 - compressed_size / original_size) if original_size else 0.0,
        )
        return (original_size, compressed_size)

    def combine_documents(
        self,
        sources: list[Path],
        output_path: Path,
        *,
        progress_callback=None,
    ) -> int:
        """PR 16: combine multiple PDFs into a new document.

        Concatenates ``sources`` in order using ``pymupdf.Document.insert_pdf``.
        Each source contributes a contiguous run of pages to the output; the
        first source's pages become the target's pages 0..N_1-1, the second
        source's become pages N_1..N_1+N_2-1, and so on. Annotations (including
        pending redaction marks) are preserved by PyMuPDF's copy pipeline.

        Style collision resolution across pending redactions from different
        sources is applied by ``_reconcile_combined_groups`` (sub-step 4);
        this sub-step is the plain concat.

        Args:
            sources: paths to PDFs to concatenate, in order.
            output_path: destination file path.
            progress_callback: optional ``callable(current, total)``
                where current is the number of sources processed so
                far and total is len(sources).

        Returns:
            total page count of the combined document.

        Raises:
            DocumentSaveError: on any I/O or PyMuPDF failure.
        """
        if not sources:
            raise DocumentSaveError("Cannot combine: no sources provided")

        target = pymupdf.open()
        try:
            total = len(sources)
            for idx, source_path in enumerate(sources):
                if progress_callback is not None:
                    try:
                        progress_callback(idx, total)
                    except Exception:
                        pass
                if not source_path.exists():
                    raise DocumentSaveError(f"Cannot combine: source does not exist: {source_path}")
                try:
                    source_doc = pymupdf.open(str(source_path))
                except Exception as exc:
                    raise DocumentSaveError(f"Cannot open source {source_path}: {exc}") from exc
                try:
                    if source_doc.needs_pass:
                        msg = (
                            "Cannot combine encrypted source without "
                            f"decryption first: {source_path}"
                        )
                        raise DocumentSaveError(msg)
                    target.insert_pdf(source_doc)
                finally:
                    source_doc.close()
            # Fire final progress
            if progress_callback is not None:
                try:
                    progress_callback(total, total)
                except Exception:
                    pass
            page_count = target.page_count
            try:
                target.save(
                    str(output_path),
                    garbage=4,
                    deflate=True,
                    clean=True,
                )
            except (OSError, RuntimeError) as exc:
                raise DocumentSaveError(f"Combine save failed: {exc}") from exc
        finally:
            target.close()

        # PR 16: reopen the saved file and reconcile style collisions
        # across pending redaction groups per the locked last-source-wins
        # rule. Cannot happen before first save because PyMuPDF's
        # annotation iterator does not surface annots from non-first
        # insert_pdf calls until the doc is flattened.
        try:
            reopened = pymupdf.open(str(output_path))
        except Exception as exc:
            raise DocumentSaveError(
                f"Cannot reopen combined doc for reconciliation: {exc}"
            ) from exc
        try:
            reconciled = self._reconcile_combined_groups(reopened)
            if reconciled > 0:
                # PyMuPDF disallows non-incremental save to the source
                # path, so we write to a temp path and rename. This
                # gives us full-rewrite semantics (no stale annotation
                # data left behind).
                temp_path = output_path.with_name(
                    output_path.stem + ".reconciling" + output_path.suffix
                )
                try:
                    reopened.save(
                        str(temp_path),
                        garbage=4,
                        deflate=True,
                        clean=True,
                    )
                except (OSError, RuntimeError) as exc:
                    raise DocumentSaveError(f"Reconciled save failed: {exc}") from exc
                # Close before rename so the OS releases the file handle.
                reopened.close()
                try:
                    temp_path.replace(output_path)
                except OSError as exc:
                    raise DocumentSaveError(f"Reconciled swap failed: {exc}") from exc
                return page_count
        finally:
            if not reopened.is_closed:
                reopened.close()

        logger.info(
            "Combined %d source(s) into %s (%d pages)",
            len(sources),
            output_path.name,
            page_count,
        )
        return page_count

    def extract_words_with_boxes(
        self,
    ) -> list[tuple[int, tuple[float, float, float, float], str]]:
        """PR 17a: extract all words with bounding boxes for diff.

        Returns a flat list of ``(page_index, bbox, word)`` tuples
        in document reading order. Each ``bbox`` is a ``(x0, y0, x1, y1)``
        rectangle in PDF coordinates.

        Uses PyMuPDF's ``page.get_text("words")`` which returns
        ``(x0, y0, x1, y1, word, block_no, line_no, word_no)`` tuples.
        We drop the block/line/word indices -- the caller only needs
        the bbox for highlight rendering.

        Whitespace-only "words" are excluded. Case and punctuation
        are preserved as-is; the diff caller decides normalization.

        Raises:
            DocumentClosedError: if no document is open.
        """
        self._require_open()
        assert self._doc is not None
        result: list[tuple[int, tuple[float, float, float, float], str]] = []
        for page_index in range(self._doc.page_count):
            page = self._doc[page_index]
            for word_tuple in page.get_text("words"):
                x0, y0, x1, y1, word = word_tuple[:5]
                if not word or not word.strip():
                    continue
                result.append((page_index, (x0, y0, x1, y1), word))
        return result

    def _reconcile_combined_groups(self, target_doc) -> int:
        """PR 16: apply last-source-wins reconciliation to combined doc.

        After concat, groups may contain marks with divergent styling
        (e.g. source A had "John Smith" red, source B had "John Smith"
        green). Our design principle is group-atomic: all marks in a
        group share styling by design. So we reconcile: for each group
        with divergent marks, adopt the styling of the mark with the
        highest page_index (which comes from the latest source by
        construction, since insert_pdf appends pages in order).

        Session Global values are not needed for reconciliation --
        we don't care about the Custom/Global label at this point,
        only the actual stored fill/text. Callers determine label
        later via ``list_redactions_grouped`` with their own session
        values.

        The reconciliation operates on ``target_doc`` directly (a
        ``pymupdf.Document``), not on the adapter's ``self._doc``,
        because Combine builds a fresh output doc that never becomes
        the adapter's current document.

        Returns the number of groups that were reconciled (0 if none
        had divergent styling).
        """
        # Group by normalized extracted text using local helpers.
        # We do not use self.list_redactions_grouped here because
        # target_doc is not self._doc.
        groups: dict[str, list] = {}
        for page_index in range(target_doc.page_count):
            page = target_doc[page_index]
            for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                rect = annot.rect
                text = page.get_textbox(rect) or ""
                normalized = self._normalize_group_text(text)
                if not normalized:
                    # Region-based singleton -- unique per (page, rect),
                    # so no collision possible. Skip.
                    continue
                # Read this mark's fill/text
                fill_color = (0, 0, 0)
                if annot.colors and annot.colors.get("fill"):
                    fill = annot.colors["fill"]
                    fill_color = tuple(int(round(c * 255)) for c in fill)
                replacement_text = annot.info.get("content") or None
                groups.setdefault(normalized, []).append(
                    {
                        "page_index": page_index,
                        "rect": (rect.x0, rect.y0, rect.x1, rect.y1),
                        "fill_color": fill_color,
                        "replacement_text": replacement_text,
                    }
                )

        reconciled = 0
        for normalized_text, marks in groups.items():
            if len(marks) < 2:
                continue  # singleton -- no collision possible
            # Find distinct styles in this group
            styles = {(m["fill_color"], m["replacement_text"]) for m in marks}
            if len(styles) < 2:
                continue  # already uniform -- no reconciliation needed
            # Divergent styling. Pick the mark with highest page_index
            # -- that's from the latest source.
            winner = max(marks, key=lambda m: m["page_index"])
            winning_fill = winner["fill_color"]
            winning_text = winner["replacement_text"]
            # Apply to every mark in the group. We use delete+recreate
            # (matches update_redaction_group semantics) so text updates
            # take effect on the underlying OverlayText.
            fill_float = tuple(c / 255.0 for c in winning_fill)
            for page_index in range(target_doc.page_count):
                page = target_doc[page_index]
                to_recreate: list[tuple[float, float, float, float]] = []
                for annot in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]):
                    rect = annot.rect
                    text = page.get_textbox(rect) or ""
                    if self._normalize_group_text(text) != normalized_text:
                        continue
                    to_recreate.append((rect.x0, rect.y0, rect.x1, rect.y1))
                # Delete matching, then re-add with winning values
                for annot in list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
                    rt = (
                        annot.rect.x0,
                        annot.rect.y0,
                        annot.rect.x1,
                        annot.rect.y1,
                    )
                    if rt in to_recreate:
                        page.delete_annot(annot)
                for rt in to_recreate:
                    rect = pymupdf.Rect(*rt)
                    kwargs: dict = {"fill": fill_float, "cross_out": True}
                    if winning_text is not None:
                        kwargs["text"] = winning_text
                    new_annot = page.add_redact_annot(rect, **kwargs)
                    if winning_text is not None:
                        info = new_annot.info
                        info["content"] = winning_text
                        new_annot.set_info(info)
                        new_annot.update()
            reconciled += 1

        if reconciled > 0:
            logger.info(
                "Reconciled %d group(s) with divergent styling (last-source-wins)",
                reconciled,
            )
        return reconciled

    def _recompress_embedded_images(
        self,
        *,
        jpeg_quality: int,
        image_dpi: int,
        progress_callback,
    ) -> None:
        """PR 15: rewrite embedded images via PyMuPDF's ``rewrite_images``.

        Uses PyMuPDF's built-in image rewriting rather than a hand-rolled
        Pillow pipeline. The built-in correctly maintains xref metadata
        (Width / Height / Filter / ColorSpace), handles alpha channels,
        CMYK, and undecodable formats without silent corruption.

        DPI semantics: we expose a single ``image_dpi`` (target) to the
        caller. Internally we set ``dpi_threshold`` slightly higher than
        the target (1.33x) so images already close to the target are
        left alone -- avoids re-encoding artefacts on images that don't
        need it. PyMuPDF requires dpi_target < dpi_threshold.

        Progress callback fires once before and once after the rewrite
        since rewrite_images has no per-image hook. Callers relying on
        determinate progress should treat this as a "busy" indicator
        instead.
        """
        assert self._doc is not None

        if progress_callback is not None:
            try:
                progress_callback(0, 1)
            except Exception:
                pass

        # Target DPI must be < threshold DPI per PyMuPDF constraint.
        # Use 1.33x buffer (150 DPI target -> 200 DPI threshold).
        dpi_threshold = max(int(image_dpi * 1.33), image_dpi + 1)

        try:
            self._doc.rewrite_images(
                dpi_threshold=dpi_threshold,
                dpi_target=image_dpi,
                quality=jpeg_quality,
                lossy=True,
                lossless=True,
                bitonal=False,
                color=True,
                gray=True,
            )
        except Exception as exc:
            # rewrite_images can fail on unusual color spaces or protected
            # image encodings. Log and continue -- the rest of compression
            # (font subsetting, garbage collection) still applies.
            logger.info("rewrite_images skipped: %s", exc)

        if progress_callback is not None:
            try:
                progress_callback(1, 1)
            except Exception:
                pass

    def _encryption_save_kwargs(
        self,
        spec: EncryptionSpec | None,
    ) -> dict:
        """Translate an ``EncryptionSpec`` into PyMuPDF save kwargs.

        ``None`` on ``spec`` means 'preserve current encryption state'
        (PR 10.5 preserve-encryption invariant). PyMuPDF's default on
        a bare save() is to STRIP encryption, so when the current doc
        is encrypted we must explicitly re-encrypt the output with
        the stored password. Unencrypted -> unencrypted output;
        encrypted -> encrypted output. No accidental decryption.

        Invalid specs (owner_password set with user_password=None)
        raise ``DocumentSaveError`` before any I/O happens.
        """
        if spec is None:
            # PR 10.5 preserve-encryption invariant.
            if self._doc is not None and self._is_encrypted_at_open:
                if self._current_password is None:
                    # Should never happen -- open() only succeeds if
                    # a password authenticated -- but guard anyway.
                    raise DocumentSaveError("Cannot preserve encryption: no stored password")
                return {
                    "encryption": pymupdf.PDF_ENCRYPT_AES_256,
                    "user_pw": self._current_password,
                    "owner_pw": self._current_password,
                }
            return {}
        if spec.user_password is None and spec.owner_password is not None:
            raise DocumentSaveError(
                "Invalid EncryptionSpec: owner_password requires a "
                "user_password (owner-only encryption is not supported)."
            )
        if spec.user_password is None:
            # Remove encryption: strip both passwords and use NONE.
            return {
                "encryption": pymupdf.PDF_ENCRYPT_NONE,
                "user_pw": "",
                "owner_pw": "",
            }
        # Add or change password.
        # Owner password defaults to user_password when unspecified.
        owner = spec.owner_password if spec.owner_password is not None else spec.user_password
        # PR 10.5 hard-codes AES-256; algorithm field on the spec
        # is reserved for future dialog exposure.
        return {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "user_pw": spec.user_password,
            "owner_pw": owner,
        }

    def new_document(self) -> None:
        """Open a new empty in-memory PDF; close any prior open doc."""
        self.close()
        self._doc = pymupdf.open()
        self._path = None
        self._is_dirty = False

    def insert_pdf(
        self,
        source: "PyMuPDFAdapter",
        from_index: int,
        to_index: int,
        at_index: int,
    ) -> None:
        """Insert source[from_index..to_index] (inclusive) before at_index."""
        self._require_open()
        assert self._doc is not None
        # Validate source is open. We deliberately reach for the
        # private _doc attribute -- insert_pdf is engine-internal
        # (PyMuPDF's Document.insert_pdf wants a pymupdf.Document
        # for the source) and we only have one adapter implementation.
        src_doc = getattr(source, "_doc", None)
        if src_doc is None:
            raise PageOperationError("insert_pdf: source adapter has no open document")
        src_count = src_doc.page_count
        if from_index < 0 or from_index >= src_count:
            raise PageOutOfRangeError(
                f"insert_pdf: from_index {from_index} out of range [0, {src_count})"
            )
        if to_index < from_index or to_index >= src_count:
            raise PageOutOfRangeError(
                f"insert_pdf: to_index {to_index} out of range [{from_index}, {src_count})"
            )
        target_count = self._doc.page_count
        if at_index < 0 or at_index > target_count:
            raise PageOutOfRangeError(
                f"insert_pdf: at_index {at_index} out of range [0, {target_count}]"
            )
        # PyMuPDF: start_at=-1 means append; else insert before that
        # 0-based index in the destination. Our contract uses
        # target_count to mean append, so translate.
        start_at = -1 if at_index == target_count else at_index
        self._doc.insert_pdf(
            src_doc,
            from_page=from_index,
            to_page=to_index,
            start_at=start_at,
        )
        self._is_dirty = True
