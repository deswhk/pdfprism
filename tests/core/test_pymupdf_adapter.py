"""Tests for PyMuPDFAdapter."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.document import DocumentAdapter
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
    OutlineItem,
    PageInfo,
    Redaction,
    SearchHit,
)

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

    def test_duplicate_last_page(self, mutable_adapter, sample_pdf_path) -> None:
        # Regression: PyMuPDF rejects fullcopy_page(N, N+1) when N+1 ==
        # page_count. The adapter uses target=-1 (append) in that case.
        a = mutable_adapter
        a.open(sample_pdf_path)
        last = a.page_count - 1
        a.duplicate_page(last)
        assert a.page_count == 4


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


class TestNewDocument:
    def test_creates_empty_doc(self) -> None:
        a = PyMuPDFAdapter()
        try:
            a.new_document()
            assert a.page_count == 0
            assert a.is_dirty is False
        finally:
            a.close()

    def test_closes_any_open_doc(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        try:
            a.open(sample_pdf_path)
            assert a.page_count > 0
            a.new_document()
            assert a.page_count == 0
        finally:
            a.close()

    def test_save_without_path_raises(self) -> None:
        a = PyMuPDFAdapter()
        try:
            a.new_document()
            with pytest.raises(DocumentSaveError):
                a.save()
        finally:
            a.close()

    def test_save_after_insert_writes_file(self, mutable_pdf_path: Path, tmp_path: Path) -> None:
        # PyMuPDF refuses to save a zero-page document, so we insert at
        # least one page before saving. This is the realistic use case
        # for new_document anyway -- it is always followed by insert_pdf.
        target = PyMuPDFAdapter()
        source = PyMuPDFAdapter()
        try:
            target.new_document()
            source.open(mutable_pdf_path)
            target.insert_pdf(source, 0, 0, 0)
            out = tmp_path / "out.pdf"
            target.save(out)
            assert out.exists()
            assert target.is_dirty is False
        finally:
            target.close()
            source.close()


class TestInsertPdf:
    def _open_source(self, mutable_pdf_path: Path) -> PyMuPDFAdapter:
        a = PyMuPDFAdapter()
        a.open(mutable_pdf_path)
        return a

    def test_insert_all_pages_into_empty(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            target.insert_pdf(source, 0, source.page_count - 1, 0)
            assert target.page_count == source.page_count
            assert target.is_dirty is True
        finally:
            target.close()
            source.close()

    def test_insert_partial_range(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            target.insert_pdf(source, 1, 2, 0)
            assert target.page_count == 2
        finally:
            target.close()
            source.close()

    def test_append_using_target_page_count(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            target.insert_pdf(source, 0, 0, 0)
            target.insert_pdf(source, 1, 1, target.page_count)
            assert target.page_count == 2
        finally:
            target.close()
            source.close()

    def test_insert_preserves_source(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            before = source.page_count
            target.new_document()
            target.insert_pdf(source, 0, source.page_count - 1, 0)
            assert source.page_count == before
            assert source.is_dirty is False
        finally:
            target.close()
            source.close()

    def test_insert_at_middle_of_existing(self, mutable_pdf_path: Path) -> None:
        # Insert source pages between existing target pages.
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            # First fill target with 2 pages from source
            target.insert_pdf(source, 0, 1, 0)
            # Now insert a single page at position 1 (between them)
            target.insert_pdf(source, 2, 2, 1)
            assert target.page_count == 3
        finally:
            target.close()
            source.close()

    def test_source_not_open_raises(self) -> None:
        target = PyMuPDFAdapter()
        unopened = PyMuPDFAdapter()
        try:
            target.new_document()
            with pytest.raises(PageOperationError, match="no open document"):
                target.insert_pdf(unopened, 0, 0, 0)
        finally:
            target.close()

    def test_from_index_out_of_range_raises(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            with pytest.raises(PageOutOfRangeError, match="from_index"):
                target.insert_pdf(source, 99, 99, 0)
        finally:
            target.close()
            source.close()

    def test_to_index_below_from_raises(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            with pytest.raises(PageOutOfRangeError, match="to_index"):
                target.insert_pdf(source, 2, 0, 0)
        finally:
            target.close()
            source.close()

    def test_at_index_out_of_range_raises(self, mutable_pdf_path: Path) -> None:
        target = PyMuPDFAdapter()
        source = self._open_source(mutable_pdf_path)
        try:
            target.new_document()
            with pytest.raises(PageOutOfRangeError, match="at_index"):
                target.insert_pdf(source, 0, 0, 99)
        finally:
            target.close()
            source.close()


# ---- PR 10: password path ---------------------------------------------


class TestEncryptedOpen:
    """PyMuPDFAdapter.open with the password parameter."""

    # ---- Positive cases ------------------------------------------------

    def test_correct_password_opens(self, encrypted_pdf_path: Path) -> None:
        """Positive: right password -> opens normally."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            assert adapter.page_count == 1
        finally:
            adapter.close()

    def test_needs_password_true_before_open_flag(self, encrypted_pdf_path: Path) -> None:
        """Positive: the DocumentInfo carries needs_password=True.

        After a successful authenticated open, ``needs_password`` still
        reports the *original* state of the document, not the currently-
        authenticated state. This is intentional -- ``needs_password``
        answers 'was this encrypted?' not 'am I authenticated now?'.
        """
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            info = adapter.get_document_info()
            assert info.needs_password is True
        finally:
            adapter.close()

    def test_password_ignored_on_unencrypted_pdf(self, sample_pdf_path: Path) -> None:
        """Positive (design invariant Q4): passing a password on an
        unencrypted PDF is silently accepted -- PyMuPDF's authenticate()
        no-ops for unencrypted docs. This lets callers pass a password
        without first probing needs_password."""
        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path, password="hunter2")
        try:
            assert adapter.page_count == 3
            assert adapter.get_document_info().needs_password is False
        finally:
            adapter.close()

    # ---- Negative cases ------------------------------------------------

    def test_missing_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: no password on encrypted PDF -> PasswordRequiredError."""
        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path)

    def test_empty_string_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: empty string treated as wrong password."""
        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path, password="")

    def test_wrong_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: wrong password -> PasswordRequiredError."""
        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path, password="wrong")

    def test_none_password_raises(self, encrypted_pdf_path: Path) -> None:
        """Negative: explicit None -> same behavior as missing arg."""
        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path, password=None)

    def test_failed_auth_leaves_adapter_closed(self, encrypted_pdf_path: Path) -> None:
        """Negative: on auth failure the adapter must not hold a doc.

        Otherwise a naive caller could re-attempt operations on an
        adapter that thinks it has a document, and get confusing errors.
        Verified by trying to use the adapter after failed open --
        should raise (because _require_open catches it).
        """
        from pdfprism.core.exceptions import DocumentOpenError

        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path, password="wrong")
        # Adapter should not hold an authenticated doc.
        with pytest.raises((DocumentOpenError, AssertionError, AttributeError)):
            _ = adapter.page_count

    def test_retry_after_failed_auth_works(self, encrypted_pdf_path: Path) -> None:
        """Positive: same adapter can retry after a failed attempt.

        Real UX flow: user types wrong password, then correct one on
        the same adapter instance. Must not require constructing a fresh
        adapter each attempt.
        """
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            adapter.open(encrypted_pdf_path, password="wrong")
        # Now retry with the correct password on the SAME adapter.
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            assert adapter.page_count == 1
        finally:
            adapter.close()


# ---- PR 10.5: encryption round-trips on save --------------------------


class TestEncryptionSaveRoundTrip:
    """PyMuPDFAdapter.save(encryption=EncryptionSpec(...)) round-trips."""

    # ---- Positive cases -------------------------------------------------

    def test_add_password_to_unencrypted_pdf(self, mutable_pdf_path: Path, tmp_path: Path) -> None:
        """Positive: unencrypted -> encrypted, correct password authenticates."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            out = tmp_path / "add_password.pdf"
            adapter.save(
                out,
                encryption=EncryptionSpec(user_password="hunter2"),
            )
        finally:
            adapter.close()

        # Reopen: should now require password
        verifier = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            verifier.open(out)
        # Correct password opens
        verifier.open(out, password="hunter2")
        try:
            assert verifier.get_document_info().needs_password is True
        finally:
            verifier.close()

    def test_change_password_on_encrypted_pdf(
        self, encrypted_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: encrypted with pw A -> save with pw B; A fails, B works."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            out = tmp_path / "changed_password.pdf"
            adapter.save(
                out,
                encryption=EncryptionSpec(user_password="new_password"),
            )
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        # Old password should NOT open the new file
        with pytest.raises(PasswordRequiredError):
            verifier.open(out, password=ENCRYPTED_PDF_PASSWORD)
        # New password does
        verifier.open(out, password="new_password")
        try:
            assert verifier.page_count == 1  # from encrypted fixture
        finally:
            verifier.close()

    def test_remove_password_from_encrypted_pdf(
        self, encrypted_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: encrypted -> save with EncryptionSpec(None) -> unencrypted."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            out = tmp_path / "removed_password.pdf"
            adapter.save(
                out,
                encryption=EncryptionSpec(user_password=None),
            )
        finally:
            adapter.close()

        # Reopen with NO password should succeed
        verifier = PyMuPDFAdapter()
        verifier.open(out)  # no password kwarg
        try:
            assert verifier.get_document_info().needs_password is False
        finally:
            verifier.close()

    def test_explicit_owner_password_different_from_user(
        self, mutable_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: explicit owner_pw different from user_pw round-trips.

        PyMuPDF's authenticate() accepts either; we test that the user
        password opens the file (owner-password permission semantics
        arrive with PR 11).
        """
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            out = tmp_path / "explicit_owner.pdf"
            adapter.save(
                out,
                encryption=EncryptionSpec(
                    user_password="userpw",
                    owner_password="ownerpw",
                ),
            )
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        verifier.open(out, password="userpw")
        try:
            assert verifier.page_count == 3  # sample.pdf pages
        finally:
            verifier.close()

    def test_in_place_save_with_new_password(self, mutable_pdf_path: Path) -> None:
        """Positive: default-path save with encryption change round-trips.

        Uses the existing in-place temp-file dance; adapter stays
        usable afterward because save() re-opens + authenticates.
        """
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.save(encryption=EncryptionSpec(user_password="hunter2"))
            # Adapter should still be usable post-save (re-opened +
            # authenticated internally)
            assert adapter.page_count == 3
            info = adapter.get_document_info()
            assert info.needs_password is True
        finally:
            adapter.close()

    def test_save_as_with_encryption_leaves_source_untouched(
        self, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive: save-as with encryption -> source stays unencrypted."""
        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        try:
            out = tmp_path / "encrypted_copy.pdf"
            adapter.save(
                out,
                encryption=EncryptionSpec(user_password="secret"),
            )
        finally:
            adapter.close()

        # Source unchanged: still opens without password
        src_verifier = PyMuPDFAdapter()
        src_verifier.open(sample_pdf_path)  # no password
        try:
            assert src_verifier.get_document_info().needs_password is False
        finally:
            src_verifier.close()

    def test_none_encryption_preserves_unencrypted_state(
        self, mutable_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive (preserve invariant): save(encryption=None) on
        unencrypted PDF leaves output unencrypted."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            out = tmp_path / "still_unencrypted.pdf"
            adapter.save(out)  # encryption defaults to None
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        verifier.open(out)
        try:
            assert verifier.get_document_info().needs_password is False
        finally:
            verifier.close()

    def test_none_encryption_preserves_encrypted_state(
        self, encrypted_pdf_path: Path, tmp_path: Path
    ) -> None:
        """Positive (preserve invariant): save(encryption=None) on
        encrypted PDF leaves output encrypted with the same password."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            out = tmp_path / "still_encrypted.pdf"
            adapter.save(out)  # encryption=None
        finally:
            adapter.close()

        verifier = PyMuPDFAdapter()
        with pytest.raises(PasswordRequiredError):
            verifier.open(out)
        # Same password still works
        verifier.open(out, password=ENCRYPTED_PDF_PASSWORD)
        try:
            assert verifier.get_document_info().needs_password is True
        finally:
            verifier.close()

    # ---- Negative cases -------------------------------------------------

    def test_owner_only_encryption_rejected(self, mutable_pdf_path: Path, tmp_path: Path) -> None:
        """Negative: EncryptionSpec(user_password=None, owner_password='x')
        raises DocumentSaveError before any I/O."""
        from pdfprism.core.exceptions import DocumentSaveError

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            out = tmp_path / "should_not_be_written.pdf"
            with pytest.raises(DocumentSaveError, match="owner-only"):
                adapter.save(
                    out,
                    encryption=EncryptionSpec(
                        user_password=None,
                        owner_password="ownerpw",
                    ),
                )
            # Fast-fail: no temp file or output file left behind.
            assert not out.exists()
        finally:
            adapter.close()

    def test_save_without_open_raises(self, tmp_path: Path) -> None:
        """Negative regression: save on unopened adapter still raises."""
        from pdfprism.core.exceptions import DocumentOpenError

        adapter = PyMuPDFAdapter()
        with pytest.raises(DocumentOpenError):
            adapter.save(
                tmp_path / "never.pdf",
                encryption=EncryptionSpec(user_password="x"),
            )


# ---- PR 10.5 regression: PyMuPDF 1.27.x needs_pass-de-auth bug -----------


class TestNeedsPassDoesNotDeAuthenticate:
    """Guard against a PyMuPDF 1.27.x quirk that PR 10.5 originally tripped.

    Reading ``doc.needs_pass`` on an authenticated encrypted document
    silently de-authenticates it -- subsequent text extraction and page
    rendering return empty. The adapter must therefore *never* read
    ``self._doc.needs_pass`` after ``open()`` completes; it should use
    ``self._is_encrypted_at_open`` (a snapshot captured before auth) for
    any subsequent state check.

    These tests exercise the code paths that would previously have
    de-authenticated the doc: ``get_document_info()``, and any operation
    that touches the encryption state after open.
    """

    def test_get_document_info_does_not_de_auth(self, encrypted_pdf_path: Path) -> None:
        """Positive: calling get_document_info() on an authenticated
        encrypted doc must not break subsequent text extraction."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            # Pre-check: text works right after open
            page_before = adapter._doc.load_page(0)
            # Encrypted fixture has minimal text but page loads should work
            _ = page_before.get_text()

            # Call the operation that previously de-authenticated the doc
            info = adapter.get_document_info()
            assert info.needs_password is True

            # Text extraction must still work after get_document_info
            # (this would return empty pre-fix)
            page_after = adapter._doc.load_page(0)
            # If de-auth happened, load_page or get_text would fail/return empty
            _ = page_after.get_text()

            # Render must also still work
            pix = adapter._doc.load_page(0).get_pixmap()
            assert pix.width > 0 and pix.height > 0
        finally:
            adapter.close()

    def test_repeated_get_document_info_does_not_de_auth(self, encrypted_pdf_path: Path) -> None:
        """Positive: multiple info calls in a row still leave the doc usable."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            for _ in range(5):
                info = adapter.get_document_info()
                assert info.needs_password is True
            # After 5 info calls, the doc must still be authenticated:
            # load_page + render still work.
            pix = adapter._doc.load_page(0).get_pixmap()
            assert pix.width > 0
        finally:
            adapter.close()

    def test_render_page_after_get_document_info_works(self, encrypted_pdf_path: Path) -> None:
        """Positive: the exact sequence the app uses -- info followed by
        render_page -- must produce a real (non-blank) pixmap."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        adapter = PyMuPDFAdapter()
        adapter.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            _ = adapter.get_document_info()  # the trigger, previously
            # Render via the adapter's public method
            png_bytes = adapter.render_page(0, zoom=1.0)
            # Non-empty PNG. Pre-fix this would produce a blank output.
            assert len(png_bytes) > 100

            # Also confirm the doc's page still has text (fixture is
            # minimal but present -- verify by comparing to a fresh
            # authenticated pymupdf open).
            import pymupdf

            probe = pymupdf.open(str(encrypted_pdf_path))
            probe.authenticate(ENCRYPTED_PDF_PASSWORD)
            expected_text_len = len(probe.load_page(0).get_text())
            probe.close()

            adapter_text_len = len(adapter._doc.load_page(0).get_text())
            assert adapter_text_len == expected_text_len, (
                f"Adapter text extraction returned {adapter_text_len} chars "
                f"but fresh authenticated PyMuPDF returned {expected_text_len}. "
                "This indicates the adapter's _doc has been de-authenticated."
            )
        finally:
            adapter.close()

    def test_snapshot_flag_matches_open_time_state(
        self, encrypted_pdf_path: Path, mutable_pdf_path: Path
    ) -> None:
        """Positive: _is_encrypted_at_open reflects the encryption state
        at open() time, and stays stable across operations."""
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        # Encrypted case
        adapter1 = PyMuPDFAdapter()
        adapter1.open(encrypted_pdf_path, password=ENCRYPTED_PDF_PASSWORD)
        try:
            assert adapter1._is_encrypted_at_open is True
            # Stays true after other operations
            _ = adapter1.get_document_info()
            assert adapter1._is_encrypted_at_open is True
        finally:
            adapter1.close()
        # After close, flag resets
        assert adapter1._is_encrypted_at_open is False

        # Unencrypted case
        adapter2 = PyMuPDFAdapter()
        adapter2.open(mutable_pdf_path)
        try:
            assert adapter2._is_encrypted_at_open is False
        finally:
            adapter2.close()


# ---- PR 11: metadata read/write ----------------------------------------


class TestGetMetadata:
    """PyMuPDFAdapter.get_metadata reads the six Info dict fields."""

    def test_reads_standard_fields(self, mutable_pdf_path: Path) -> None:
        """Positive: doc with metadata -> dict has all six keys."""
        # First set some known metadata via PyMuPDF directly so we can
        # read it back through the adapter.
        import pymupdf

        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata(
                {
                    "title": "Test Doc",
                    "author": "Test Author",
                    "subject": "Testing",
                    "keywords": "unit, test",
                    "creator": "pytest",
                    "producer": "PyMuPDF",
                }
            )
            raw.save(str(mutable_pdf_path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            meta = adapter.get_metadata()
            assert meta["title"] == "Test Doc"
            assert meta["author"] == "Test Author"
            assert meta["subject"] == "Testing"
            assert meta["keywords"] == "unit, test"
        finally:
            adapter.close()

    def test_empty_metadata_normalized_to_none(self, mutable_pdf_path: Path) -> None:
        """Positive: PyMuPDF empty strings surface as None."""
        import pymupdf

        # Wipe every Info field on the fixture so we know we're testing
        # the None-normalization path, not a fixture-authoring artefact.
        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata(
                {
                    k: ""
                    for k in (
                        "title",
                        "author",
                        "subject",
                        "keywords",
                        "creator",
                        "producer",
                    )
                }
            )
            raw.save(str(mutable_pdf_path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            meta = adapter.get_metadata()
            assert meta["author"] is None
            assert meta["title"] is None
        finally:
            adapter.close()

    def test_returns_all_six_keys(self, mutable_pdf_path: Path) -> None:
        """Positive: dict always has the six standard keys, even if None."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            meta = adapter.get_metadata()
            expected_keys = {"title", "author", "subject", "keywords", "creator", "producer"}
            assert set(meta.keys()) == expected_keys
        finally:
            adapter.close()


class TestSetMetadata:
    """PyMuPDFAdapter.set_metadata mutates Info dict fields."""

    def test_single_field_update_preserves_others(self, mutable_pdf_path: Path) -> None:
        """Positive: updating title alone leaves other fields alone."""
        import pymupdf

        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata({"author": "Original Author"})
            raw.save(str(mutable_pdf_path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.set_metadata({"title": "New Title"})
            adapter.save()
        finally:
            adapter.close()

        verify = PyMuPDFAdapter()
        verify.open(mutable_pdf_path)
        try:
            meta = verify.get_metadata()
            assert meta["title"] == "New Title"
            assert meta["author"] == "Original Author"
        finally:
            verify.close()

    def test_multiple_fields_at_once(self, mutable_pdf_path: Path) -> None:
        """Positive: all fields in the dict get applied."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.set_metadata(
                {
                    "title": "Multi Title",
                    "author": "Multi Author",
                    "subject": "Multi Subject",
                }
            )
            adapter.save()
        finally:
            adapter.close()

        verify = PyMuPDFAdapter()
        verify.open(mutable_pdf_path)
        try:
            meta = verify.get_metadata()
            assert meta["title"] == "Multi Title"
            assert meta["author"] == "Multi Author"
            assert meta["subject"] == "Multi Subject"
        finally:
            verify.close()

    def test_none_value_clears_field(self, mutable_pdf_path: Path) -> None:
        """Positive: passing None for a field wipes it."""
        import pymupdf

        raw = pymupdf.open(str(mutable_pdf_path))
        try:
            raw.set_metadata({"title": "To Be Cleared"})
            raw.save(str(mutable_pdf_path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        finally:
            raw.close()

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.set_metadata({"title": None})
            adapter.save()
        finally:
            adapter.close()

        verify = PyMuPDFAdapter()
        verify.open(mutable_pdf_path)
        try:
            assert verify.get_metadata()["title"] is None
        finally:
            verify.close()

    def test_unknown_key_ignored(self, mutable_pdf_path: Path) -> None:
        """Negative: unknown key doesn't raise; also doesn't sneak into metadata."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.set_metadata({"title": "Real", "badkey": "junk"})
            # No exception. The bad key should not appear in a subsequent read.
            meta = adapter.get_metadata()
            assert meta["title"] == "Real"
            assert "badkey" not in meta
        finally:
            adapter.close()

    def test_marks_dirty(self, mutable_pdf_path: Path) -> None:
        """Positive: set_metadata sets the dirty flag."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.is_dirty is False
            adapter.set_metadata({"title": "Making Dirty"})
            assert adapter.is_dirty is True
        finally:
            adapter.close()


class TestDeleteXmlMetadata:
    """PyMuPDFAdapter.delete_xml_metadata removes the XMP stream."""

    def test_call_does_not_raise(self, mutable_pdf_path: Path) -> None:
        """Positive: works whether or not XMP is present."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.delete_xml_metadata()  # sample.pdf has no XMP; must not raise
        finally:
            adapter.close()

    def test_marks_dirty(self, mutable_pdf_path: Path) -> None:
        """Positive: sets dirty flag."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.delete_xml_metadata()
            assert adapter.is_dirty is True
        finally:
            adapter.close()


# ---- PR 11: permissions read/write ----------------------------------

# ---- PR 12: adapter redaction tests -------------------------------------


class TestAddRedaction:
    """PyMuPDFAdapter.add_redaction creates a redact annotation."""

    def test_creates_annotation(self, mutable_pdf_path: Path) -> None:
        """Positive: after add_redaction, list_redactions has one entry."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            r = Redaction(page_index=0, rect=(50.0, 50.0, 200.0, 100.0))
            adapter.add_redaction(r)
            pending = adapter.list_redactions()
            assert len(pending) == 1
            assert pending[0].page_index == 0
        finally:
            adapter.close()

    def test_rect_preserved(self, mutable_pdf_path: Path) -> None:
        """Positive: the annotation's rect matches what we passed."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            r = Redaction(page_index=0, rect=(72.0, 100.0, 300.0, 130.0))
            adapter.add_redaction(r)
            pending = adapter.list_redactions()
            # Float precision from PDF round-trip -- allow small tolerance
            got = pending[0].rect
            for expected, actual in zip((72.0, 100.0, 300.0, 130.0), got, strict=True):
                assert abs(expected - actual) < 0.5, f"{expected} vs {actual}"
        finally:
            adapter.close()

    def test_marks_dirty(self, mutable_pdf_path: Path) -> None:
        """Positive: add_redaction sets the dirty flag."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.is_dirty is False
            adapter.add_redaction(Redaction(page_index=0, rect=(10.0, 10.0, 50.0, 30.0)))
            assert adapter.is_dirty is True
        finally:
            adapter.close()

    def test_page_out_of_range(self, mutable_pdf_path: Path) -> None:
        """Negative: page_index >= page_count raises PageOutOfRangeError."""
        from pdfprism.core.exceptions import PageOutOfRangeError

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(PageOutOfRangeError):
                adapter.add_redaction(Redaction(page_index=999, rect=(0.0, 0.0, 10.0, 10.0)))
        finally:
            adapter.close()


class TestListRedactions:
    """PyMuPDFAdapter.list_redactions returns pending marks."""

    def test_empty_doc_returns_empty_list(self, mutable_pdf_path: Path) -> None:
        """Positive: no redactions -> empty list."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.list_redactions() == []
        finally:
            adapter.close()

    def test_page_major_order(self, mutable_pdf_path: Path) -> None:
        """Positive: redactions returned in page-major order.

        Only works if the fixture has at least 2 pages -- if not,
        skip. sample.pdf is 2-page.
        """
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            if adapter.page_count < 2:
                pytest.skip("Fixture has fewer than 2 pages")
            # Add one to page 1 first, then to page 0. Expect them back
            # in page-order (0 first, 1 second).
            adapter.add_redaction(Redaction(page_index=1, rect=(10.0, 10.0, 50.0, 30.0)))
            adapter.add_redaction(Redaction(page_index=0, rect=(20.0, 20.0, 60.0, 40.0)))
            pending = adapter.list_redactions()
            assert len(pending) == 2
            assert pending[0].page_index == 0
            assert pending[1].page_index == 1
        finally:
            adapter.close()

    def test_read_only_does_not_mark_dirty(self, mutable_pdf_path: Path) -> None:
        """Positive: list_redactions is a read; it does not mark dirty."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.list_redactions()
            # Adapter dirty flag stays False (nothing was mutated).
            assert adapter.is_dirty is False
        finally:
            adapter.close()


class TestRemoveRedaction:
    """PyMuPDFAdapter.remove_redaction deletes a specific pending mark."""

    def test_removes_target_only(self, mutable_pdf_path: Path) -> None:
        """Positive: remove_redaction leaves other marks intact."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.add_redaction(Redaction(page_index=0, rect=(10.0, 10.0, 50.0, 30.0)))
            adapter.add_redaction(Redaction(page_index=0, rect=(100.0, 100.0, 200.0, 150.0)))
            assert len(adapter.list_redactions()) == 2
            adapter.remove_redaction(page_index=0, redaction_index=0)
            remaining = adapter.list_redactions()
            assert len(remaining) == 1
            # The remaining one should be the second rect (100, 100, 200, 150).
            got = remaining[0].rect
            assert abs(got[0] - 100.0) < 0.5
        finally:
            adapter.close()

    def test_page_out_of_range(self, mutable_pdf_path: Path) -> None:
        """Negative: page_index invalid -> PageOutOfRangeError."""
        from pdfprism.core.exceptions import PageOutOfRangeError

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(PageOutOfRangeError):
                adapter.remove_redaction(page_index=999, redaction_index=0)
        finally:
            adapter.close()

    def test_redaction_index_out_of_range(self, mutable_pdf_path: Path) -> None:
        """Negative: redaction_index >= count on that page -> IndexError."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(IndexError):
                adapter.remove_redaction(page_index=0, redaction_index=0)
        finally:
            adapter.close()


class TestApplyRedactions:
    """PyMuPDFAdapter.apply_redactions destructively commits pending marks."""

    def test_destroys_text_under_mark(self, mutable_pdf_path: Path, tmp_path: Path) -> None:
        """Positive: text within the redaction rect is gone after apply."""
        # Fresh fixture with known text

        import pymupdf

        p_test = tmp_path / "apply_test.pdf"
        # Create a PDF with two lines of text
        d = pymupdf.open()
        page = d.new_page(width=612, height=792)
        page.insert_text((72, 200), "SECRET_TEXT_ABC", fontsize=14)
        page.insert_text((72, 250), "keep this line", fontsize=12)
        d.save(str(p_test))
        d.close()

        # Use text search to get the exact rect of SECRET_TEXT_ABC
        d = pymupdf.open(str(p_test))
        matches = d.load_page(0).search_for("SECRET_TEXT_ABC")
        assert matches, "Setup: SECRET_TEXT_ABC not found in fixture"
        r = matches[0]
        d.close()

        adapter = PyMuPDFAdapter()
        adapter.open(p_test)
        try:
            adapter.add_redaction(
                Redaction(
                    page_index=0,
                    rect=(r.x0, r.y0, r.x1, r.y1),
                )
            )
            count = adapter.apply_redactions()
            assert count == 1
            adapter.save()
        finally:
            adapter.close()

        # Reopen and verify
        d = pymupdf.open(str(p_test))
        text = d.load_page(0).get_text()
        d.close()
        assert "SECRET_TEXT_ABC" not in text, f"Text should be redacted: {text!r}"
        assert "keep this line" in text, f"Other text should survive: {text!r}"

    def test_returns_count_applied(self, mutable_pdf_path: Path) -> None:
        """Positive: apply_redactions returns the number of marks committed."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.add_redaction(Redaction(page_index=0, rect=(10.0, 10.0, 50.0, 30.0)))
            if adapter.page_count > 1:
                adapter.add_redaction(Redaction(page_index=1, rect=(10.0, 10.0, 50.0, 30.0)))
                expected = 2
            else:
                expected = 1
            count = adapter.apply_redactions()
            assert count == expected
        finally:
            adapter.close()

    def test_empty_doc_returns_zero(self, mutable_pdf_path: Path) -> None:
        """Positive: nothing pending -> apply returns 0."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.apply_redactions() == 0
        finally:
            adapter.close()

    def test_pending_empty_after_apply(self, mutable_pdf_path: Path) -> None:
        """Positive: annotations are consumed by apply; list is now empty."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.add_redaction(Redaction(page_index=0, rect=(10.0, 10.0, 50.0, 30.0)))
            assert len(adapter.list_redactions()) == 1
            adapter.apply_redactions()
            assert adapter.list_redactions() == []
        finally:
            adapter.close()


class TestAddRedactionsForWords:
    """PR 12.1: batch redaction from Word list."""

    def test_batch_adds_per_word(self, mutable_pdf_path: Path) -> None:
        """Positive: N Words -> N redaction annots + returns N."""
        from pdfprism.core.types import Word

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            words = [
                Word(text="A", x0=10.0, y0=10.0, x1=20.0, y1=25.0),
                Word(text="B", x0=25.0, y0=10.0, x1=40.0, y1=25.0),
                Word(text="C", x0=45.0, y0=10.0, x1=60.0, y1=25.0),
            ]
            count = adapter.add_redactions_for_words(page_index=0, words=words)
            assert count == 3
            assert len(adapter.list_redactions()) == 3
        finally:
            adapter.close()

    def test_empty_words_returns_zero(self, mutable_pdf_path: Path) -> None:
        """Positive: empty list -> 0, dirty flag unchanged."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.is_dirty is False
            count = adapter.add_redactions_for_words(page_index=0, words=[])
            assert count == 0
            assert adapter.is_dirty is False
        finally:
            adapter.close()

    def test_invalid_page_index(self, mutable_pdf_path: Path) -> None:
        """Negative: page_index out of range -> PageOutOfRangeError."""
        from pdfprism.core.exceptions import PageOutOfRangeError
        from pdfprism.core.types import Word

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            with pytest.raises(PageOutOfRangeError):
                adapter.add_redactions_for_words(
                    page_index=999,
                    words=[Word(text="x", x0=0.0, y0=0.0, x1=10.0, y1=10.0)],
                )
        finally:
            adapter.close()


class TestAddRedactionsForHits:
    """PR 12.2: batch redaction from SearchHit list."""

    def test_batch_adds_per_hit(self, mutable_pdf_path: Path) -> None:
        """Positive: N hits -> N redaction annots + returns N."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            hits = [
                SearchHit(page_index=0, x0=10.0, y0=10.0, x1=50.0, y1=25.0),
                SearchHit(page_index=0, x0=60.0, y0=10.0, x1=90.0, y1=25.0),
                SearchHit(
                    page_index=min(1, adapter.page_count - 1),
                    x0=10.0,
                    y0=10.0,
                    x1=50.0,
                    y1=25.0,
                ),
            ]
            count = adapter.add_redactions_for_hits(hits)
            assert count == 3
            assert len(adapter.list_redactions()) == 3
        finally:
            adapter.close()

    def test_empty_hits_returns_zero(self, mutable_pdf_path: Path) -> None:
        """Positive: empty list -> 0, dirty flag unchanged."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            assert adapter.is_dirty is False
            count = adapter.add_redactions_for_hits([])
            assert count == 0
            assert adapter.is_dirty is False
        finally:
            adapter.close()

    def test_invalid_page_raises(self, mutable_pdf_path: Path) -> None:
        """Negative: hit with invalid page -> PageOutOfRangeError."""
        from pdfprism.core.exceptions import PageOutOfRangeError

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            hits = [
                SearchHit(page_index=999, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
            ]
            with pytest.raises(PageOutOfRangeError):
                adapter.add_redactions_for_hits(hits)
        finally:
            adapter.close()


class TestApplyRedactionsKwargs:
    """PR 12.3: apply_redactions gains images/graphics/text kwargs."""

    def test_default_kwargs_backwards_compatible(self, mutable_pdf_path: Path) -> None:
        """Positive: default kwargs match PyMuPDF defaults; existing behavior preserved."""
        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            adapter.add_redaction(Redaction(page_index=0, rect=(10.0, 10.0, 50.0, 30.0)))
            # Explicit defaults match old hard-coded values.
            count = adapter.apply_redactions(images=2, graphics=1, text=0)
            assert count == 1
        finally:
            adapter.close()


class TestAddRedactionsForWordsKwargs:
    """PR 12.3: add_redactions_for_words respects fill_color kwarg."""

    def test_custom_fill_color(self, mutable_pdf_path: Path) -> None:
        """Positive: passing fill_color reads back through list_redactions."""
        from pdfprism.core.types import Word

        adapter = PyMuPDFAdapter()
        adapter.open(mutable_pdf_path)
        try:
            words = [Word(text="X", x0=10.0, y0=10.0, x1=50.0, y1=25.0)]
            adapter.add_redactions_for_words(page_index=0, words=words, fill_color=(255, 0, 0))
            pending = adapter.list_redactions()
            assert len(pending) == 1
            # PyMuPDF stores color as 0-1 floats; we read back as 0-255 ints
            # with round-trip precision loss.
            r, g, b = pending[0].fill_color
            assert abs(r - 255) <= 1
            assert abs(g - 0) <= 1
            assert abs(b - 0) <= 1
        finally:
            adapter.close()
