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

    Thin today because the adapter's ``search_page`` already does the heavy
    lifting; this layer exists because a future PR adds case-sensitive and
    whole-word matching by extracting text and filtering above the adapter,
    which is a service concern, not an adapter concern.
    """

    def __init__(self, adapter: DocumentAdapter) -> None:
        self._adapter = adapter

    def find_all(self, term: str) -> list[SearchHit]:
        """Return all matches of ``term`` across the document in page order.

        Empty term returns an empty list. Matching is case-insensitive for
        ASCII characters (delegated to the adapter).
        """
        if not term:
            return []
        hits: list[SearchHit] = []
        for page_index in range(self._adapter.page_count):
            hits.extend(self._adapter.search_page(page_index, term))
        logger.debug("find_all(%r) -> %d hit(s)", term, len(hits))
        return hits

    @staticmethod
    def find_all_across(
        adapters: list[DocumentAdapter],
        term: str,
    ) -> list[CrossDocHit]:
        """Search a list of adapters and return tagged hits in stable order.

        Hits are returned grouped by adapter (in the order provided) and
        within each adapter in page order. Empty term or empty adapter
        list returns an empty list.
        """
        if not term:
            return []
        results: list[CrossDocHit] = []
        for doc_index, adapter in enumerate(adapters):
            for page_index in range(adapter.page_count):
                for hit in adapter.search_page(page_index, term):
                    results.append(CrossDocHit(doc_index=doc_index, hit=hit))
        logger.debug(
            "find_all_across(%r, %d adapters) -> %d hit(s)",
            term,
            len(adapters),
            len(results),
        )
        return results
