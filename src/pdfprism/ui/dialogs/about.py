"""About dialog: version, copyright, license, source link, warranty disclaimer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import pdfprism

_BODY_HTML = """
<h2 style="margin-bottom:4px;">pdfprism {version}</h2>
<p style="color:#666;margin-top:0;">A PDF reader and editor built on PyMuPDF + PySide6.</p>

<p>Copyright &copy; 2026 deswhk</p>

<p>Licensed under the
<a href="https://www.gnu.org/licenses/agpl-3.0.html">
GNU Affero General Public License v3.0 (AGPL-3.0)</a>.<br>
Source code:
<a href="https://github.com/deswhk/pdfprism">github.com/deswhk/pdfprism</a><br>
Report issues:
<a href="https://github.com/deswhk/pdfprism/issues">github.com/deswhk/pdfprism/issues</a></p>

<h3 style="margin-bottom:4px;">No warranty</h3>
<p style="margin-top:0;">This software is provided <b>AS IS</b>, without warranty
of any kind. Test on copies; back up important files before destructive
operations. The authors do not accept responsibility for data loss.</p>

<h3 style="margin-bottom:4px;">Third-party components</h3>
<p style="margin-top:0;">pdfprism uses
<a href="https://github.com/pymupdf/PyMuPDF">PyMuPDF</a> (Artifex,
AGPL-3.0) and
<a href="https://www.qt.io/qt-for-python">PySide6</a> (Qt,
LGPL-3.0). See <code>NOTICE.txt</code> in the install for the full notice.</p>
"""


class AboutDialog(QDialog):
    """Modal About dialog: version, license, source, warranty disclaimer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About pdfprism")
        self.setMinimumWidth(520)

        body = QLabel(_BODY_HTML.format(version=pdfprism.__version__))
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        # "Close" maps to RejectRole by default; wire it explicitly.
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(body, 1)
        layout.addWidget(buttons)
