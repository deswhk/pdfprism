"""Widget tests for ManageMarksDialog (PR 14c)."""

from __future__ import annotations

from unittest.mock import MagicMock

from pdfprism.core.types import Redaction, RedactionGroup
from pdfprism.services.redaction import RedactionService
from pdfprism.ui.dialogs.manage_marks import ManageMarksDialog


def _make_group(
    text: str = "target",
    is_customized: bool = False,
    count: int = 1,
    fill_color: tuple[int, int, int] = (0, 0, 0),
    replacement_text: str | None = None,
    page_index: int = 0,
) -> RedactionGroup:
    marks = [
        Redaction(
            page_index=page_index,
            rect=(0.0, i * 20.0, 100.0, i * 20.0 + 10.0),
            fill_color=fill_color,
            replacement_text=replacement_text,
        )
        for i in range(count)
    ]
    return RedactionGroup(
        text=text,
        normalized_text=text.lower(),
        marks=marks,
        is_customized=is_customized,
    )


def _make_stub_service(groups: list[RedactionGroup]) -> MagicMock:
    service = MagicMock(spec=RedactionService)
    service.list_redactions_grouped.return_value = groups
    return service


class TestPopulation:
    def test_empty_shows_placeholder(self, qtbot) -> None:
        """Positive: no groups -> empty table + placeholder footer."""
        svc = _make_stub_service([])
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        assert dlg._table.rowCount() == 0
        assert dlg._footer.text() == "(no pending marks)"

    def test_populates_rows(self, qtbot) -> None:
        """Positive: groups render as rows with correct text/count/status."""
        groups = [
            _make_group("John Smith", is_customized=False, count=3),
            _make_group("Custom mark", is_customized=True, count=1),
        ]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        assert dlg._table.rowCount() == 2
        assert dlg._table.item(0, 1).text() == "John Smith"
        assert dlg._table.item(0, 2).text() == "3"
        assert "Global" in dlg._table.item(0, 4).text()
        assert "Custom" in dlg._table.item(1, 4).text()

    def test_footer_shows_totals(self, qtbot) -> None:
        """Positive: footer shows total marks and group count."""
        groups = [
            _make_group("a", count=2),
            _make_group("b", count=3),
        ]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        assert "5" in dlg._footer.text()
        assert "2" in dlg._footer.text()


class TestRowActions:
    def test_reset_row_calls_service_with_session_defaults(self, qtbot, monkeypatch) -> None:
        """Positive: Reset button calls update_redaction_group with session values."""
        group = _make_group("custom_group", is_customized=True, fill_color=(255, 0, 0))
        svc = _make_stub_service([group])
        svc.update_redaction_group.return_value = 1
        dlg = ManageMarksDialog(
            service=svc,
            session_fill=(0, 0, 0),
            session_text="[SESSION]",
        )
        qtbot.addWidget(dlg)
        dlg._on_reset_row(0)
        svc.update_redaction_group.assert_called_once_with("custom_group", (0, 0, 0), "[SESSION]")

    def test_reset_row_noop_for_global(self, qtbot) -> None:
        """Positive: Reset on Global group is a no-op."""
        group = _make_group("global_group", is_customized=False)
        svc = _make_stub_service([group])
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_reset_row(0)
        svc.update_redaction_group.assert_not_called()


class TestBulkOperations:
    def test_select_all_checks_all_rows(self, qtbot) -> None:
        """Positive: Select All checks every row."""
        groups = [_make_group(f"g{i}") for i in range(3)]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        assert dlg._checked_rows() == [0, 1, 2]

    def test_select_none_unchecks_all(self, qtbot) -> None:
        """Positive: Select None clears all checkboxes."""
        groups = [_make_group(f"g{i}") for i in range(3)]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        dlg._on_select_none()
        assert dlg._checked_rows() == []

    def test_reset_selected_skips_global_groups(self, qtbot) -> None:
        """Positive: Reset Selected only calls update for Custom groups."""
        groups = [
            _make_group("global_grp", is_customized=False),
            _make_group("custom_grp", is_customized=True),
        ]
        svc = _make_stub_service(groups)
        svc.update_redaction_group.return_value = 1
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        dlg._on_reset_selected()
        # Only the Custom group should have been reset
        svc.update_redaction_group.assert_called_once()
        args, _ = svc.update_redaction_group.call_args
        assert args[0] == "custom_grp"


class TestBulkButtonEnableState:
    def test_empty_selection_disables_all(self, qtbot) -> None:
        """Positive: no rows checked -> all bulk buttons disabled."""
        groups = [_make_group("g1")]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        assert dlg._edit_selected_button.isEnabled() is False
        assert dlg._reset_selected_button.isEnabled() is False
        assert dlg._remove_selected_button.isEnabled() is False

    def test_any_selection_enables_edit_remove(self, qtbot) -> None:
        """Positive: >= 1 row checked enables Edit + Remove."""
        groups = [_make_group("g1")]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        assert dlg._edit_selected_button.isEnabled() is True
        assert dlg._remove_selected_button.isEnabled() is True

    def test_only_global_disables_reset(self, qtbot) -> None:
        """Positive: only Global rows checked -> Reset disabled."""
        groups = [_make_group("global_grp", is_customized=False)]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        assert dlg._reset_selected_button.isEnabled() is False

    def test_customized_selected_enables_reset(self, qtbot) -> None:
        """Positive: at least one Custom row checked -> Reset enabled."""
        groups = [
            _make_group("global_grp", is_customized=False),
            _make_group("custom_grp", is_customized=True),
        ]
        svc = _make_stub_service(groups)
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        dlg._on_select_all()
        assert dlg._reset_selected_button.isEnabled() is True


class TestChangedSignal:
    def test_reset_row_emits_changed(self, qtbot) -> None:
        """Positive: successful mutation emits changed signal."""
        group = _make_group("g", is_customized=True)
        svc = _make_stub_service([group])
        svc.update_redaction_group.return_value = 1
        dlg = ManageMarksDialog(service=svc, session_fill=(0, 0, 0), session_text=None)
        qtbot.addWidget(dlg)
        received: list = []
        dlg.changed.connect(received.append)
        dlg._on_reset_row(0)
        assert received == [1]
