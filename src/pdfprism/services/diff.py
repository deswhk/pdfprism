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

        logger.info(
            "Diff: %d word(s) added, %d word(s) deleted across %d/%d pages",
            result.additions_count,
            result.deletions_count,
            len(result.pages_touched_a),
            len(result.pages_touched_b),
        )
        return result
