"""Document-wide text search."""

import logging
from enum import Enum

from pdfprism.core.document import DocumentAdapter
from pdfprism.core.types import CrossDocHit, SearchHit

logger = logging.getLogger(__name__)


class SearchScope(Enum):
    """Search scope: current document only, or every open document."""

    CURRENT = "current"
    ALL_OPEN = "all_open"


class SearchService:
    """Aggregates per-page search hits into a single document-ordered list.

    Two paths:

    * **Fast path** (default, case-insensitive substring): delegates to
      ``DocumentAdapter.search_page``, which uses PyMuPDF's native search
      with ``quads=True`` so highlights follow text orientation on
      rotated pages.
    * **Slow path** (``case_sensitive=True`` or ``whole_word=True``):
      iterates ``DocumentAdapter.extract_words`` and filters in Python.
      Hits cover whole words even when the term is a substring. On
      rotated pages the slow path yields axis-aligned bounding rects
      because ``get_text("words")`` does not expose quads -- a
      documented limitation, acceptable for the rare combination of
      rotated content and case-sensitive / whole-word search.
    """

    def __init__(self, adapter: DocumentAdapter) -> None:
        self._adapter = adapter

    @staticmethod
    def _search_one_adapter(
        adapter: DocumentAdapter,
        term: str,
        case_sensitive: bool,
        whole_word: bool,
    ) -> list[SearchHit]:
        """Run a search against a single adapter.

        Dispatches fast vs. slow path on the flags. Returns hits in page
        order. Empty term returns an empty list.
        """
        if not term:
            return []

        hits: list[SearchHit] = []
        if not case_sensitive and not whole_word:
            for page_index in range(adapter.page_count):
                hits.extend(adapter.search_page(page_index, term))
            return hits

        # Slow path: extract words and filter in Python.
        term_lower = term.lower()
        for page_index in range(adapter.page_count):
            for word in adapter.extract_words(page_index):
                text = word.text
                if whole_word:
                    if case_sensitive:
                        match = text == term
                    else:
                        match = text.lower() == term_lower
                else:
                    if case_sensitive:
                        match = term in text
                    else:
                        match = term_lower in text.lower()
                if match:
                    hits.append(
                        SearchHit(
                            page_index=page_index,
                            x0=word.x0,
                            y0=word.y0,
                            x1=word.x1,
                            y1=word.y1,
                        )
                    )
        return hits

    def find_all(
        self,
        term: str,
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> list[SearchHit]:
        """Return all matches of ``term`` across the document in page order.

        Empty term returns an empty list. Default behavior is
        case-insensitive substring match (same as PR 4). ``case_sensitive``
        and ``whole_word`` opt into the slow path.
        """
        hits = self._search_one_adapter(self._adapter, term, case_sensitive, whole_word)
        logger.debug("find_all(%r) -> %d hit(s)", term, len(hits))
        return hits

    @staticmethod
    def find_all_across(
        adapters: list[DocumentAdapter],
        term: str,
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> list[CrossDocHit]:
        """Search a list of adapters and return tagged hits in stable order.

        Hits are grouped by adapter (in the order provided) and within
        each adapter in page order. Empty term or empty adapter list
        returns an empty list. Flag semantics match :meth:`find_all`.
        """
        if not term:
            return []
        results: list[CrossDocHit] = []
        for doc_index, adapter in enumerate(adapters):
            hits = SearchService._search_one_adapter(adapter, term, case_sensitive, whole_word)
            for hit in hits:
                results.append(CrossDocHit(doc_index=doc_index, hit=hit))
        logger.debug(
            "find_all_across(%r, %d adapters) -> %d hit(s)",
            term,
            len(adapters),
            len(results),
        )
        return results
