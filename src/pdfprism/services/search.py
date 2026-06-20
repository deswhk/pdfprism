"""Document-wide text search."""

import logging

from pdfprism.core.document import DocumentAdapter
from pdfprism.core.types import SearchHit

logger = logging.getLogger(__name__)


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
