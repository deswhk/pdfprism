"""Properties dialog: metadata view/edit + one-click sanitize (PR 11).

Single-tab layout for this PR (permissions deferred to potential PR 11.5).
Loads current metadata into six text fields (title, author, subject,
keywords, creator, producer), lets the user edit, and provides two
security shortcuts:

- **Sanitize All** clears the six Info-dict fields immediately (visual
  confirmation of what will happen). User can still change fields
  before OK, or Cancel to abort entirely.

- **Delete embedded XMP metadata stream** checkbox controls whether
  the PDF 2.0 XMP metadata stream is also removed on OK. XMP can
  carry redundant author/creator info that survives Info-dict
  clearing; the checkbox defaults to checked so a sanitize is
  complete by default.

The dialog is dumb: it holds initial metadata + edits, exposes
``get_updates()`` and ``delete_xmp_requested`` for the caller to apply.
No service or adapter dependency at construction time -- MainWindow
wires them together.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PropertiesDialog(QDialog):
    """Metadata view/edit dialog with sanitize shortcut."""

    _FIELDS = (
        ("title", "Title"),
        ("author", "Author"),
        ("subject", "Subject"),
        ("keywords", "Keywords"),
        ("creator", "Creator"),
        ("producer", "Producer"),
    )

    def __init__(
        self,
        current_metadata: dict[str, str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        self.setModal(True)

        self._editors: dict[str, QLineEdit] = {}
        self._build_ui(current_metadata)

    def _build_ui(self, current: dict[str, str | None]) -> None:
        layout = QVBoxLayout(self)

        header = QLabel("Metadata")
        header.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(header)

        form = QFormLayout()
        for key, label in self._FIELDS:
            editor = QLineEdit()
            editor.setText(current.get(key) or "")
            editor.setPlaceholderText("(empty)")
            self._editors[key] = editor
            form.addRow(label + ":", editor)
        layout.addLayout(form)

        # Separator between edit fields and the sanitize controls
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Sanitize + XMP controls sit together as related "security"
        # affordances.
        self._sanitize_button = QPushButton("Sanitize All Fields")
        self._sanitize_button.setToolTip(
            "Clear all metadata fields. Nothing is saved until you click OK."
        )
        self._sanitize_button.clicked.connect(self._on_sanitize)
        layout.addWidget(self._sanitize_button)

        self._delete_xmp = QCheckBox("Delete embedded XMP metadata stream")
        self._delete_xmp.setToolTip(
            "XMP is a separate metadata stream (PDF 2.0). It can carry\n"
            "redundant author/creator info that survives clearing the Info\n"
            "dictionary. Checking this removes it on OK."
        )
        self._delete_xmp.setChecked(True)
        layout.addWidget(self._delete_xmp)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---- Slots ----

    def _on_sanitize(self) -> None:
        """Clear all editor fields immediately for visual feedback."""
        for editor in self._editors.values():
            editor.clear()

    # ---- Public accessors (called after exec() by caller) ----

    def get_updates(self) -> dict[str, str | None]:
        """Return the current editor state as a dict.

        Empty strings are preserved as empty strings; the SERVICE layer
        maps empty -> None. Caller receives what the user actually typed.
        """
        return {key: editor.text() for key, editor in self._editors.items()}

    @property
    def delete_xmp_requested(self) -> bool:
        """Whether the "delete XMP" checkbox is checked at OK time."""
        return self._delete_xmp.isChecked()
