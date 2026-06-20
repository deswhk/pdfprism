"""Search bar widget for in-document text search."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class SearchBar(QWidget):
    """Acrobat-style search bar shown at the top of the main window.

    Pure UI shell: emits intent signals when the user submits or navigates,
    displays a result counter that is fed in from the outside. Doesn't know
    about the document, the service, or the page view. MainWindow wires
    those connections in step 7d.

    Signals:
        find_requested(str): user submitted a non-empty search term.
        next_requested(): user clicked Next (or pressed F3, wired by
            MainWindow).
        prev_requested(): user clicked Previous (or pressed Shift+F3).
        closed(): user clicked the close button or pressed Escape inside
            the input field.
    """

    find_requested = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in document")
        self._input.setClearButtonEnabled(True)
        self._input.returnPressed.connect(self._on_return_pressed)
        self._input.installEventFilter(self)

        self._prev_btn = QPushButton("Previous")
        self._prev_btn.clicked.connect(self.prev_requested)

        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self.next_requested)

        self._counter_label = QLabel("")
        self._counter_label.setMinimumWidth(96)
        self._counter_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._close_btn = QPushButton("X")
        self._close_btn.setFixedWidth(28)
        self._close_btn.setToolTip("Close (Esc)")
        self._close_btn.clicked.connect(self.closed)

        layout.addWidget(self._input, stretch=1)
        layout.addWidget(self._prev_btn)
        layout.addWidget(self._next_btn)
        layout.addWidget(self._counter_label)
        layout.addWidget(self._close_btn)

    @property
    def search_term(self) -> str:
        return self._input.text()

    def focus_input(self) -> None:
        """Focus the input box and select any existing text."""
        self._input.setFocus()
        self._input.selectAll()

    def set_match_count(self, current: int, total: int) -> None:
        """Update the counter label.

        ``total == 0`` shows "No matches" regardless of ``current``.
        ``total > 0`` shows "current of total" (1-based current).
        """
        if total == 0:
            self._counter_label.setText("No matches")
        else:
            self._counter_label.setText(f"{current} of {total}")

    def clear(self) -> None:
        """Empty the input and the counter."""
        self._input.clear()
        self._counter_label.setText("")

    def _on_return_pressed(self) -> None:
        term = self._input.text().strip()
        if term:
            self.find_requested.emit(term)

    def eventFilter(  # noqa: N802
        self, watched: QObject, event: QEvent
    ) -> bool:
        if watched is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.closed.emit()
                return True
        return super().eventFilter(watched, event)
