"""Go-to-page dialog (Ctrl+G)."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QWidget,
)


class GotoPageDialog(QDialog):
    """Modal dialog asking for a 1-based page number.

    Read the user's choice via ``page_number`` after ``exec()`` returns
    ``QDialog.DialogCode.Accepted``.
    """

    def __init__(
        self,
        current_page_1based: int,
        page_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to page")

        self._spin = QSpinBox()
        self._spin.setRange(1, page_count)
        self._spin.setValue(current_page_1based)
        self._spin.selectAll()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(f"Page (1 - {page_count}):", self._spin)
        layout.addRow(buttons)

    @property
    def page_number(self) -> int:
        """1-based page number selected by the user."""
        return self._spin.value()
