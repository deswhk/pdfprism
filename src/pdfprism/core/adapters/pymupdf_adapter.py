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
