"""Application Qt Style Sheets.

Loaded by ``MainWindow`` and applied via ``QApplication.setStyleSheet``.
Setting an empty string clears any active stylesheet and returns the app
to the platform default.
"""

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #2b2b2b;
    color: #e0e0e0;
}

QMenuBar {
    background-color: #2b2b2b;
    color: #e0e0e0;
}
QMenuBar::item:selected {
    background-color: #404040;
}

QMenu {
    background-color: #353535;
    color: #e0e0e0;
    border: 1px solid #555555;
}
QMenu::item:selected {
    background-color: #4a4a4a;
}
QMenu::separator {
    background-color: #555555;
    height: 1px;
}

QToolBar {
    background-color: #2b2b2b;
    border: none;
    spacing: 2px;
}
QToolButton {
    background-color: transparent;
    color: #e0e0e0;
    padding: 4px;
    border-radius: 3px;
}
QToolButton:hover {
    background-color: #404040;
}
QToolButton:disabled {
    color: #707070;
}

QStatusBar {
    background-color: #2b2b2b;
    color: #e0e0e0;
}

QDockWidget {
    color: #e0e0e0;
}
QDockWidget::title {
    background-color: #353535;
    padding-left: 5px;
}

QListView, QTreeView {
    background-color: #1e1e1e;
    color: #e0e0e0;
    selection-background-color: #0078d4;
    selection-color: #ffffff;
}

QLineEdit {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #555555;
    padding: 2px;
    border-radius: 3px;
}

QPushButton {
    background-color: #353535;
    color: #e0e0e0;
    border: 1px solid #555555;
    padding: 4px 12px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #404040;
}
QPushButton:pressed {
    background-color: #1e1e1e;
}

QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #2b2b2b;
    border: none;
}
QScrollBar::handle {
    background-color: #555555;
    border-radius: 3px;
}
QScrollBar::handle:hover {
    background-color: #707070;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    background: none;
}

QTabBar::tab {
    background-color: #353535;
    color: #e0e0e0;
    padding: 4px 10px;
    border: 1px solid #555555;
}
QTabBar::tab:selected {
    background-color: #4a4a4a;
}
"""
