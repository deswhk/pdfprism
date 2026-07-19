"""Diff service (PR 17a).

Compares two documents word-by-word and returns a structured diff
result. This module is UI-agnostic: all types are pure Python
dataclasses; the DiffService only depends on the adapter for
word extraction.

The diff algorithm is standard sequence matching (Python's
``difflib.SequenceMatcher``). We compare word sequences with
case-sensitive matching by default. Whitespace-only tokens are
already filtered by the adapter, so no additional normalization
is needed here.

This is a text-only diff: it does not detect moved sections
(a paragraph moved from page 3 to page 5 will appear as both a
deletion on page 3 and an insertion on page 5). See ARCHITECTURE.md
for the design decision to defer layout-aware comparison to a
future PR.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Literal

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

logger = logging.getLogger(__name__)


@dataclass
class WordRef:
    """A word located in a source document.

    ``bbox`` is (x0, y0, x1, y1) in PDF coordinates on the source page.
    """

    page_index: int
    bbox: tuple[float, float, float, float]
    word: str


@dataclass
class DiffRegion:
    """A contiguous change span from the diff.

    - ``kind=equal``: both sides identical
    - ``kind=delete``: content in A only
    - ``kind=insert``: content in B only
    - ``kind=replace``: content differs between A and B

    ``words_a`` is empty for pure inserts; ``words_b`` is empty for
    pure deletes.
    """

    kind: Literal["equal", "delete", "insert", "replace"]
    words_a: list[WordRef] = field(default_factory=list)
    words_b: list[WordRef] = field(default_factory=list)


@dataclass
class ImageRef:
    """An embedded image located in a source document.

    ``bbox`` is (x0, y0, x1, y1) in PDF coordinates on the source page.
    ``image_hash`` is the MD5 hex digest of the raw image bytes,
    used for identity comparison.
    """

    page_index: int
    bbox: tuple[float, float, float, float]
    image_hash: str


@dataclass
class ImageDiff:
    """A detected image change between two documents.

    - ``kind=added``: image in B has no match in A
    - ``kind=removed``: image in A has no match in B
    - ``kind=replaced``: matched pair with differing bytes

    ``left`` is None for "added"; ``right`` is None for "removed".
    """

    kind: Literal["added", "removed", "replaced"]
    left: ImageRef | None = None
    right: ImageRef | None = None


@dataclass
class DiffResult:
    """Complete diff of two documents.

    ``additions_count`` and ``deletions_count`` are word counts.
    ``pages_touched_*`` sets identify pages that contain at least
    one changed word in each document.
    """

    regions: list[DiffRegion] = field(default_factory=list)
    additions_count: int = 0
    deletions_count: int = 0
    pages_touched_a: set[int] = field(default_factory=set)
    pages_touched_b: set[int] = field(default_factory=set)
    # PR 17b: image-level differences
    image_diffs: list[ImageDiff] = field(default_factory=list)
    image_changes_count: int = 0


class DiffService:
    """Compute a word-level diff between two documents."""

    def diff_documents(
        self,
        adapter_a: PyMuPDFAdapter,
        adapter_b: PyMuPDFAdapter,
        *,
        case_sensitive: bool = True,
    ) -> DiffResult:
        """Compare two open documents word-by-word.

        Both adapters must have documents open. The comparison uses
        ``PyMuPDFAdapter.extract_words_with_boxes`` to get the word
        sequences, then runs ``difflib.SequenceMatcher`` to find the
        change regions.

        Args:
            adapter_a: adapter with the "left" document open.
            adapter_b: adapter with the "right" document open.
            case_sensitive: if False, uppercase both sides before
                matching (bboxes/original casing preserved in output).

        Returns:
            Structured ``DiffResult`` with change regions and totals.
        """
        words_a = [
            WordRef(page_index=pi, bbox=bbox, word=w)
            for pi, bbox, w in adapter_a.extract_words_with_boxes()
        ]
        words_b = [
            WordRef(page_index=pi, bbox=bbox, word=w)
            for pi, bbox, w in adapter_b.extract_words_with_boxes()
        ]

        # Build the sequences for matching. If case-insensitive,
        # compare on lowered strings; original ``word`` strings on
        # the WordRef objects stay as-is for display.
        seq_a = [w.word if case_sensitive else w.word.lower() for w in words_a]
        seq_b = [w.word if case_sensitive else w.word.lower() for w in words_b]

        matcher = difflib.SequenceMatcher(a=seq_a, b=seq_b, autojunk=False)
        result = DiffResult()

        for op, a_start, a_end, b_start, b_end in matcher.get_opcodes():
            region_words_a = words_a[a_start:a_end]
            region_words_b = words_b[b_start:b_end]
            # difflib op names map to our kinds. "equal" and "replace"
            # match directly; "delete" and "insert" also match.
            region = DiffRegion(
                kind=op,  # type: ignore[arg-type]
                words_a=region_words_a,
                words_b=region_words_b,
            )
            result.regions.append(region)
            if op in ("delete", "replace"):
                result.deletions_count += len(region_words_a)
                for w in region_words_a:
                    result.pages_touched_a.add(w.page_index)
            if op in ("insert", "replace"):
                result.additions_count += len(region_words_b)
                for w in region_words_b:
                    result.pages_touched_b.add(w.page_index)

        # PR 17b: image-level diffing (position-based matching)
        self._diff_images(adapter_a, adapter_b, result)

        logger.info(
            "Diff: %d word(s) added, %d word(s) deleted across %d/%d pages",
            result.additions_count,
            result.deletions_count,
            len(result.pages_touched_a),
            len(result.pages_touched_b),
        )
        if result.image_changes_count > 0:
            logger.info(
                "Diff: %d image change(s) detected",
                result.image_changes_count,
            )
        return result

    def _diff_images(
        self,
        adapter_a: PyMuPDFAdapter,
        adapter_b: PyMuPDFAdapter,
        result: DiffResult,
    ) -> None:
        """PR 17b: position-based image diffing.

        For each page, match A's images to B's images by bbox center
        distance (tolerance 20 pt). Matched pairs with differing MD5
        hashes are ``replaced``. Unmatched A images are ``removed``;
        unmatched B images are ``added``. Cross-page matching is not
        attempted -- an image moved from page 3 to page 5 will show as
        removed on page 3 + added on page 5.

        Populates ``result.image_diffs`` and ``result.image_changes_count``.
        """
        images_a = adapter_a.extract_images_with_bboxes()
        images_b = adapter_b.extract_images_with_bboxes()

        # Convert to ImageRef with hashes, grouped per page
        refs_a: dict[int, list[ImageRef]] = {}
        for pi, bbox, raw in images_a:
            h = hashlib.md5(raw).hexdigest()
            refs_a.setdefault(pi, []).append(ImageRef(page_index=pi, bbox=bbox, image_hash=h))
        refs_b: dict[int, list[ImageRef]] = {}
        for pi, bbox, raw in images_b:
            h = hashlib.md5(raw).hexdigest()
            refs_b.setdefault(pi, []).append(ImageRef(page_index=pi, bbox=bbox, image_hash=h))

        # For each page in either doc, match by proximity
        all_pages = sorted(set(refs_a.keys()) | set(refs_b.keys()))
        tolerance = 20.0  # pt

        for page_index in all_pages:
            page_a = list(refs_a.get(page_index, []))
            page_b = list(refs_b.get(page_index, []))

            # Match greedily by closest center distance
            used_b: set[int] = set()
            for ref_a in page_a:
                cx_a = (ref_a.bbox[0] + ref_a.bbox[2]) / 2
                cy_a = (ref_a.bbox[1] + ref_a.bbox[3]) / 2
                best_idx = -1
                best_dist = float("inf")
                for i, ref_b in enumerate(page_b):
                    if i in used_b:
                        continue
                    cx_b = (ref_b.bbox[0] + ref_b.bbox[2]) / 2
                    cy_b = (ref_b.bbox[1] + ref_b.bbox[3]) / 2
                    dist = ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5
                    if dist < best_dist and dist <= tolerance:
                        best_dist = dist
                        best_idx = i
                if best_idx >= 0:
                    ref_b = page_b[best_idx]
                    used_b.add(best_idx)
                    if ref_a.image_hash != ref_b.image_hash:
                        result.image_diffs.append(
                            ImageDiff(kind="replaced", left=ref_a, right=ref_b)
                        )
                        result.image_changes_count += 1
                else:
                    result.image_diffs.append(ImageDiff(kind="removed", left=ref_a, right=None))
                    result.image_changes_count += 1

            # Any unmatched B images on this page = added
            for i, ref_b in enumerate(page_b):
                if i not in used_b:
                    result.image_diffs.append(ImageDiff(kind="added", left=None, right=ref_b))
                    result.image_changes_count += 1
