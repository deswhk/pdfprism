"""Tests for PyMuPDFAdapter."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.document import DocumentAdapter
from pdfprism.core.exceptions import (
    DocumentOpenError,
    PageOperationError,
    PageOutOfRangeError,
)
from pdfprism.core.types import DocumentInfo, OutlineItem, PageInfo, SearchHit

# PNG file signature
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def adapter() -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    yield a
    a.close()


@pytest.fixture
def opened_adapter(adapter: PyMuPDFAdapter, sample_pdf_path: Path) -> PyMuPDFAdapter:
    adapter.open(sample_pdf_path)
    return adapter


@pytest.fixture
def mutable_adapter(adapter: PyMuPDFAdapter, mutable_pdf_path: Path) -> PyMuPDFAdapter:
    """Adapter opened on a writable copy of sample.pdf for mutation tests."""
    adapter.open(mutable_pdf_path)
    return adapter


def test_adapter_satisfies_protocol(adapter: PyMuPDFAdapter) -> None:
    assert isinstance(adapter, DocumentAdapter)


class TestOpen:
    def test_open_valid_pdf(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.page_count == 3

    def test_open_missing_file_raises(
        self, adapter: PyMuPDFAdapter, missing_pdf_path: Path
    ) -> None:
        with pytest.raises(DocumentOpenError, match="File not found"):
            adapter.open(missing_pdf_path)

    def test_open_garbage_raises(self, adapter: PyMuPDFAdapter, garbage_file: Path) -> None:
        with pytest.raises(DocumentOpenError):
            adapter.open(garbage_file)

    def test_open_second_document_closes_first(
        self, adapter: PyMuPDFAdapter, sample_pdf_path: Path
    ) -> None:
        adapter.open(sample_pdf_path)
        adapter.open(sample_pdf_path)
        assert adapter.page_count == 3


class TestPageCount:
    def test_page_count_without_open_raises(self, adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(DocumentOpenError, match="No document is currently open"):
            _ = adapter.page_count


class TestDocumentInfo:
    def test_metadata_fields(self, opened_adapter: PyMuPDFAdapter) -> None:
        info = opened_adapter.get_document_info()
        assert isinstance(info, DocumentInfo)
        assert info.page_count == 3
        assert info.title == "pdfprism sample"
        assert info.author == "deswhk"
        assert info.subject == "Test fixture"
        assert info.is_encrypted is False
        assert info.needs_password is False


class TestPageInfo:
    def test_first_page_dimensions(self, opened_adapter: PyMuPDFAdapter) -> None:
        info = opened_adapter.get_page_info(0)
        assert isinstance(info, PageInfo)
        assert info.index == 0
        assert info.width_points == pytest.approx(612.0)
        assert info.height_points == pytest.approx(792.0)

    def test_out_of_range_positive_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.get_page_info(99)

    def test_out_of_range_negative_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.get_page_info(-1)


class TestRenderPage:
    def test_returns_png_bytes(self, opened_adapter: PyMuPDFAdapter) -> None:
        png = opened_adapter.render_page(0)
        assert png.startswith(_PNG_MAGIC)
        assert len(png) > 100

    def test_higher_zoom_is_larger(self, opened_adapter: PyMuPDFAdapter) -> None:
        small = opened_adapter.render_page(0, zoom=1.0)
        large = opened_adapter.render_page(0, zoom=2.0)
        assert len(large) > len(small)

    def test_out_of_range_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.render_page(99)


class TestClose:
    def test_close_without_open_is_noop(self) -> None:
        a = PyMuPDFAdapter()
        a.close()  # should not raise

    def test_close_is_idempotent(self, opened_adapter: PyMuPDFAdapter) -> None:
        opened_adapter.close()
        opened_adapter.close()


class TestGetOutline:
    def test_returns_outline_items(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert len(outline) == 4
        assert all(isinstance(item, OutlineItem) for item in outline)

    def test_first_chapter(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[0] == OutlineItem(level=1, title="Chapter 1: Introduction", page_index=0)

    def test_subsection_entries(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[1] == OutlineItem(level=2, title="1.1 Overview", page_index=0)
        assert outline[2] == OutlineItem(level=2, title="1.2 Background", page_index=1)

    def test_second_chapter(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[3] == OutlineItem(level=1, title="Chapter 2: Conclusion", page_index=2)


class TestSearch:
    def test_finds_known_term(self, opened_adapter: PyMuPDFAdapter) -> None:
        hits = opened_adapter.search_page(0, "pdfprism")
        assert len(hits) == 1
        assert isinstance(hits[0], SearchHit)
        assert hits[0].page_index == 0

    def test_finds_term_on_each_page(self, opened_adapter: PyMuPDFAdapter) -> None:
        # "Page" appears in "Page N of 3" on every page
        for i in range(3):
            hits = opened_adapter.search_page(i, "Page")
            assert len(hits) >= 1
            assert all(h.page_index == i for h in hits)

    def test_case_insensitive_matching(self, opened_adapter: PyMuPDFAdapter) -> None:
        upper = opened_adapter.search_page(0, "PAGE")
        lower = opened_adapter.search_page(0, "page")
        assert len(upper) == len(lower)
        assert len(upper) >= 1

    def test_missing_term_returns_empty(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.search_page(0, "thiswordisnotinthedoc") == []

    def test_empty_term_returns_empty(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.search_page(0, "") == []

    def test_out_of_range_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.search_page(99, "anything")

    def test_hit_rect_is_well_formed(self, opened_adapter: PyMuPDFAdapter) -> None:
        hits = opened_adapter.search_page(0, "pdfprism")
        assert len(hits) == 1
        h = hits[0]
        assert h.x0 > 0
        assert h.y0 > 0
        assert h.x1 > h.x0
        assert h.y1 > h.y0


class TestExtractWords:
    def test_extracts_words_on_first_page(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            words = a.extract_words(0)
        finally:
            a.close()
        assert len(words) >= 3
        texts = [w.text for w in words]
        assert "Hello" in texts
        assert "pdfprism" in texts

    def test_word_has_positive_extent(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            word = a.extract_words(0)[0]
        finally:
            a.close()
        assert word.x1 > word.x0
        assert word.y1 > word.y0

    def test_out_of_range_raises(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            with pytest.raises(PageOutOfRangeError):
                a.extract_words(99)
        finally:
            a.close()

    def test_each_page_has_words(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            for i in range(a.page_count):
                assert len(a.extract_words(i)) > 0
        finally:
            a.close()


class TestRotationProjection:
    """Rotation fix: search hits and extracted words land in layout space."""

    def test_rotated_page_hit_has_quad(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hits = a.search_page(2, "Page")
        finally:
            a.close()
        assert len(hits) == 1
        assert hits[0].quad is not None

    def test_rotated_hit_bbox_in_layout_space(self, sample_pdf_path: Path) -> None:
        """On a 90-rotated A4 page (layout 595x842), 'Page' should appear
        on the right edge (x ~490-510) rather than the upper-left where
        the unrotated coordinates would put it."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hit = a.search_page(2, "Page")[0]
        finally:
            a.close()
        assert hit.x0 > 400, f"x0={hit.x0} should be on the right side of the rotated page"
        assert hit.x1 < 595
        assert hit.y0 < 200

    def test_unrotated_page_hit_quad_is_none(self, sample_pdf_path: Path) -> None:
        """Backward compat: rotation-0 hits leave quad as None."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hits = a.search_page(0, "Page")
        finally:
            a.close()
        assert hits[0].quad is None

    def test_rotated_extract_words_in_layout_space(self, sample_pdf_path: Path) -> None:
        """extract_words projects through rotation_matrix so the slow
        path (case-sensitive / whole-word) hits also land correctly."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            words = a.extract_words(2)
        finally:
            a.close()
        page_words = [w for w in words if w.text == "Page"]
        assert len(page_words) == 1
        w = page_words[0]
        assert w.x0 > 400
        assert w.x1 < 595


class TestExtractText:
    def test_returns_first_page_text(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.extract_text(0) == "Hello from pdfprism\nPage 1 of 3\n"

    def test_each_page_has_some_text(self, opened_adapter: PyMuPDFAdapter) -> None:
        for i in range(opened_adapter.page_count):
            text = opened_adapter.extract_text(i)
            assert "Page" in text

    def test_out_of_range_positive_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.extract_text(opened_adapter.page_count)

    def test_out_of_range_negative_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.extract_text(-1)


class TestExtractImages:
    def test_returns_list(self, opened_adapter: PyMuPDFAdapter) -> None:
        images = opened_adapter.extract_images(0)
        assert isinstance(images, list)

    def test_text_only_fixture_has_no_images(self, opened_adapter: PyMuPDFAdapter) -> None:
        # sample.pdf is text-only; every page returns 0 images.
        for i in range(opened_adapter.page_count):
            assert opened_adapter.extract_images(i) == []

    def test_out_of_range_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.extract_images(opened_adapter.page_count)


class TestIsDirty:
    def test_initially_not_dirty(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.is_dirty is False

    def test_dirty_after_rotate(self, mutable_adapter: PyMuPDFAdapter) -> None:
        mutable_adapter.rotate_page(0, 90)
        assert mutable_adapter.is_dirty is True

    def test_dirty_resets_after_save(self, mutable_adapter: PyMuPDFAdapter) -> None:
        mutable_adapter.rotate_page(0, 90)
        mutable_adapter.save()
        assert mutable_adapter.is_dirty is False

    def test_close_resets_dirty(self, mutable_adapter: PyMuPDFAdapter) -> None:
        mutable_adapter.rotate_page(0, 90)
        assert mutable_adapter.is_dirty is True
        mutable_adapter.close()
        assert mutable_adapter.is_dirty is False


class TestRotatePage:
    def test_rotation_applied(self, mutable_adapter: PyMuPDFAdapter) -> None:
        # sample.pdf page 0 starts at rotation 0
        before = mutable_adapter.get_page_info(0).rotation
        mutable_adapter.rotate_page(0, 90)
        after = mutable_adapter.get_page_info(0).rotation
        assert (after - before) % 360 == 90

    def test_rotation_is_additive(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.get_page_info(0).rotation
        mutable_adapter.rotate_page(0, 90)
        mutable_adapter.rotate_page(0, 90)
        after = mutable_adapter.get_page_info(0).rotation
        assert (after - before) % 360 == 180

    def test_invalid_degrees_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOperationError, match="90, 180, or 270"):
            mutable_adapter.rotate_page(0, 45)

    def test_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            mutable_adapter.rotate_page(99, 90)


class TestDeletePages:
    def test_single_index(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        mutable_adapter.delete_pages([0])
        assert mutable_adapter.page_count == before - 1

    def test_multiple_indices_in_any_order(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        # Deliberately out-of-order with a duplicate
        mutable_adapter.delete_pages([2, 0, 0])
        assert mutable_adapter.page_count == before - 2

    def test_empty_list_is_noop(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        mutable_adapter.delete_pages([])
        assert mutable_adapter.page_count == before
        assert mutable_adapter.is_dirty is False

    def test_delete_all_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        all_indices = list(range(mutable_adapter.page_count))
        with pytest.raises(PageOperationError, match="every page"):
            mutable_adapter.delete_pages(all_indices)

    def test_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            mutable_adapter.delete_pages([0, 99])


class TestInsertBlankPage:
    def test_insert_at_zero_prepends(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        mutable_adapter.insert_blank_page(0, 100, 100)
        assert mutable_adapter.page_count == before + 1

    def test_insert_at_end_appends(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        mutable_adapter.insert_blank_page(before, 100, 100)
        assert mutable_adapter.page_count == before + 1
        last = mutable_adapter.get_page_info(before)
        assert last.width_points == 100
        assert last.height_points == 100

    def test_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            mutable_adapter.insert_blank_page(99, 100, 100)

    def test_non_positive_dimensions_raise(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOperationError, match="positive"):
            mutable_adapter.insert_blank_page(0, 0, 100)
        with pytest.raises(PageOperationError, match="positive"):
            mutable_adapter.insert_blank_page(0, 100, -1)


class TestDuplicatePage:
    def test_duplicate_increments_page_count(self, mutable_adapter: PyMuPDFAdapter) -> None:
        before = mutable_adapter.page_count
        mutable_adapter.duplicate_page(0)
        assert mutable_adapter.page_count == before + 1

    def test_duplicate_preserves_text_content(self, mutable_adapter: PyMuPDFAdapter) -> None:
        original_text = mutable_adapter.extract_text(0)
        mutable_adapter.duplicate_page(0)
        copy_text = mutable_adapter.extract_text(1)
        assert copy_text == original_text

    def test_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            mutable_adapter.duplicate_page(99)


class TestMovePage:
    def test_forward_move_to_end(self, mutable_adapter: PyMuPDFAdapter) -> None:
        t0 = mutable_adapter.extract_text(0)
        last = mutable_adapter.page_count - 1
        mutable_adapter.move_page(0, last)
        assert mutable_adapter.extract_text(last) == t0

    def test_backward_move_to_start(self, mutable_adapter: PyMuPDFAdapter) -> None:
        last = mutable_adapter.page_count - 1
        t_last = mutable_adapter.extract_text(last)
        mutable_adapter.move_page(last, 0)
        assert mutable_adapter.extract_text(0) == t_last

    def test_same_index_noop(self, mutable_adapter: PyMuPDFAdapter) -> None:
        mutable_adapter.move_page(0, 0)
        assert mutable_adapter.is_dirty is False

    def test_from_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError, match="From"):
            mutable_adapter.move_page(99, 0)

    def test_to_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError, match="To"):
            mutable_adapter.move_page(0, 99)


class TestCropPage:
    def test_crop_shrinks_cropbox(self, mutable_adapter: PyMuPDFAdapter) -> None:
        info = mutable_adapter.get_page_info(0)
        mutable_adapter.crop_page(0, (10, 20, 10, 20))
        page = mutable_adapter._doc[0]
        cb = page.cropbox
        # Width should be original - left - right
        assert abs((cb.x1 - cb.x0) - (info.width_points - 40)) < 0.01
        # Height should be original - top - bottom
        assert abs((cb.y1 - cb.y0) - (info.height_points - 20)) < 0.01

    def test_zero_margins_full_page(self, mutable_adapter: PyMuPDFAdapter) -> None:
        info = mutable_adapter.get_page_info(0)
        mutable_adapter.crop_page(0, (0, 0, 0, 0))
        page = mutable_adapter._doc[0]
        cb = page.cropbox
        assert abs((cb.x1 - cb.x0) - info.width_points) < 0.01
        assert abs((cb.y1 - cb.y0) - info.height_points) < 0.01

    def test_negative_margins_raise(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOperationError, match="non-negative"):
            mutable_adapter.crop_page(0, (-1, 0, 0, 0))

    def test_excessive_margins_raise(self, mutable_adapter: PyMuPDFAdapter) -> None:
        info = mutable_adapter.get_page_info(0)
        too_wide = info.width_points
        with pytest.raises(PageOperationError, match="zero or negative"):
            mutable_adapter.crop_page(0, (0, too_wide, 0, 0))

    def test_out_of_range_raises(self, mutable_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            mutable_adapter.crop_page(99, (0, 0, 0, 0))


class TestSave:
    def test_save_resets_dirty(self, mutable_adapter: PyMuPDFAdapter) -> None:
        mutable_adapter.rotate_page(0, 90)
        mutable_adapter.save()
        assert mutable_adapter.is_dirty is False

    def test_save_persists_mutations(
        self, mutable_adapter: PyMuPDFAdapter, mutable_pdf_path: Path
    ) -> None:
        before_pages = mutable_adapter.page_count
        mutable_adapter.duplicate_page(0)
        mutable_adapter.save()
        mutable_adapter.close()
        # Reopen and check
        verifier = type(mutable_adapter)()
        verifier.open(mutable_pdf_path)
        try:
            assert verifier.page_count == before_pages + 1
        finally:
            verifier.close()

    def test_save_as_writes_new_path(
        self,
        mutable_adapter: PyMuPDFAdapter,
        tmp_path: Path,
    ) -> None:
        new_path = tmp_path / "copy.pdf"
        mutable_adapter.rotate_page(0, 90)
        mutable_adapter.save(new_path)
        assert new_path.exists()
        assert mutable_adapter.is_dirty is False

    def test_save_without_path_when_never_opened_raises(self) -> None:
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

        a = PyMuPDFAdapter()
        # Cannot save without opening (no path tracked yet, and require_open
        # will trigger before the path check).
        with pytest.raises(Exception):  # noqa: B017,PT011 - either subclass is fine
            a.save()
