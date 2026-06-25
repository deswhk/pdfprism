"""Text and image extraction services."""

import logging
from pathlib import Path

from pdfprism.core.document import DocumentAdapter
from pdfprism.core.types import Word

logger = logging.getLogger(__name__)


class ExtractService:
    """Text and image extraction operations over a single document.

    Mirrors the ``SearchService`` shape: the bound adapter is the only
    state, instance methods do per-document work, no static cross-document
    variant since extract is intrinsically per-document.
    """

    def __init__(self, adapter: DocumentAdapter) -> None:
        self._adapter = adapter

    def text_for_page(self, page_index: int) -> str:
        """Return all text on a single page."""
        return self._adapter.extract_text(page_index)

    def text_full_document(self, page_range: range | None = None) -> str:
        """Return all text in the document, pages separated by form-feed.

        ``page_range``: optional 0-based range. Defaults to all pages.
        Form-feed (``\f``) is the conventional page separator in plain-text
        dumps of paged documents.
        """
        if page_range is None:
            page_range = range(self._adapter.page_count)
        pages = [self._adapter.extract_text(i) for i in page_range]
        return "\f".join(pages)

    def text_in_rect(
        self,
        page_index: int,
        rect: tuple[float, float, float, float],
    ) -> str:
        """Return the text whose words intersect the given rect.

        Words are joined in reading order with spaces; line breaks within
        the rect become newlines. Returns empty string if no overlap.
        Intersection is "any overlap", not "fully contained" -- matches
        how click-and-drag selection works in other viewers.
        """
        rx0, ry0, rx1, ry1 = rect
        words = self._adapter.extract_words(page_index)
        in_rect = [w for w in words if w.x0 < rx1 and w.x1 > rx0 and w.y0 < ry1 and w.y1 > ry0]
        return _join_words_as_lines(in_rect)

    def snippet_around(
        self,
        page_index: int,
        rect: tuple[float, float, float, float],
        max_chars: int = 80,
    ) -> str:
        """Return a single-line snippet of text centered on ``rect``.

        Used by cross-search results: takes the line of text containing
        the hit and trims to roughly ``max_chars``, centered on the hit's
        horizontal midpoint. Trimmed sides get ellipses.
        """
        rx0, ry0, rx1, ry1 = rect
        words = self._adapter.extract_words(page_index)
        if not words:
            return ""
        hit_y_center = (ry0 + ry1) / 2
        line_height = ry1 - ry0
        tolerance = line_height * 0.7 if line_height > 0 else 5.0
        same_line = [w for w in words if abs((w.y0 + w.y1) / 2 - hit_y_center) <= tolerance]
        if not same_line:
            return ""
        same_line.sort(key=lambda w: w.x0)
        full_line = " ".join(w.text for w in same_line)
        if len(full_line) <= max_chars:
            return full_line
        hit_x_center = (rx0 + rx1) / 2
        cumulative = 0
        target = 0
        for w in same_line:
            if w.x0 >= hit_x_center:
                target = cumulative
                break
            cumulative += len(w.text) + 1
        half = max_chars // 2
        start = max(0, target - half)
        end = min(len(full_line), start + max_chars)
        snippet = full_line[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(full_line):
            snippet = snippet + "..."
        return snippet

    def images_full_document(
        self,
        output_dir: Path,
        page_range: range | None = None,
    ) -> list[Path]:
        """Extract all images and write to ``output_dir``.

        Returns the list of written paths in extraction order. Filenames
        are ``page<N>_img<M>.<ext>`` with 1-based N (page) and M (image
        within page). Creates ``output_dir`` if it does not exist.
        """
        if page_range is None:
            page_range = range(self._adapter.page_count)
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for page_index in page_range:
            images = self._adapter.extract_images(page_index)
            for img_index, img in enumerate(images, start=1):
                filename = f"page{page_index + 1}_img{img_index}.{img.ext}"
                path = output_dir / filename
                path.write_bytes(img.data)
                written.append(path)
        logger.info("Extracted %d image(s) to %s", len(written), output_dir)
        return written


def _join_words_as_lines(words: list[Word]) -> str:
    """Join words by inferring line breaks from y-coordinate jumps.

    Sort key: (rounded y0, x0). Line break inserted whenever a word's
    y0 jumps more than half a line height past the previous word. The
    line-height threshold is bootstrapped from each word's own height.
    """
    if not words:
        return ""
    words = sorted(words, key=lambda w: (round(w.y0, 0), w.x0))
    lines: list[list[str]] = [[]]
    last_y: float | None = None
    line_threshold = 5.0
    for w in words:
        if last_y is not None and (w.y0 - last_y) > line_threshold:
            lines.append([])
        lines[-1].append(w.text)
        last_y = w.y0
        line_threshold = max(line_threshold, (w.y1 - w.y0) * 0.5)
    return "\n".join(" ".join(line) for line in lines)
