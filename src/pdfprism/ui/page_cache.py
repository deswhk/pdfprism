"""LRU pixmap cache for rendered PDF pages."""

from collections import OrderedDict
from threading import Lock
from typing import TYPE_CHECKING

from PySide6.QtGui import QPixmap

if TYPE_CHECKING:
    from pdfprism.core.document import DocumentAdapter


_DEFAULT_MAX_ENTRIES = 64


class PageCache:
    """Thread-safe LRU cache of rendered page pixmaps.

    Keyed by ``(page_index, zoom)``. Both ``PageView`` and the thumbnails
    panel render through this cache, so a page rendered for one consumer
    is reusable by the other if the zoom matches. Eviction is LRU by
    access (``get`` and ``get_or_render``); when the document changes,
    ``set_adapter`` clears the cache.
    """

    def __init__(
        self,
        adapter: "DocumentAdapter | None" = None,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._adapter = adapter
        self._max_entries = max_entries
        self._cache: OrderedDict[tuple[int, float], QPixmap] = OrderedDict()
        self._lock = Lock()

    def set_adapter(self, adapter: "DocumentAdapter | None") -> None:
        """Bind a new adapter and clear any cached pixmaps."""
        with self._lock:
            self._adapter = adapter
            self._cache.clear()

    @property
    def adapter(self) -> "DocumentAdapter | None":
        """The currently bound adapter, or None if unbound."""
        return self._adapter

    def get(self, page_index: int, zoom: float) -> QPixmap | None:
        """Return the cached pixmap without rendering. ``None`` on miss.

        A hit promotes the entry to most-recently-used.
        """
        key = (page_index, round(zoom, 4))
        with self._lock:
            pix = self._cache.get(key)
            if pix is not None:
                self._cache.move_to_end(key)
            return pix

    def get_or_render(self, page_index: int, zoom: float) -> QPixmap:
        """Return the cached pixmap, rendering and storing on miss.

        Returns an empty ``QPixmap`` if no adapter is currently bound;
        the consumer should treat this as a placeholder.
        """
        key = (page_index, round(zoom, 4))
        with self._lock:
            pix = self._cache.get(key)
            if pix is not None:
                self._cache.move_to_end(key)
                return pix
            if self._adapter is None:
                return QPixmap()
            png_bytes = self._adapter.render_page(page_index, zoom=zoom)
            pix = QPixmap()
            pix.loadFromData(png_bytes, "PNG")
            self._cache[key] = pix
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
            return pix

    def clear(self) -> None:
        """Empty the cache; leave the bound adapter alone."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        """Number of cached entries."""
        with self._lock:
            return len(self._cache)
