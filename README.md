# pdfprism

A PDF reader and editor built on PyMuPDF and PySide6.

A prism decomposes light into its components; pdfprism decomposes PDFs into theirs — pages, text, images, metadata — and gives you the tools to read them, restructure them, secure them, and put them back together.

## Status

Under active development. Milestone 1 (Reader Core) is the current focus; see [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) for the full 15-PR roadmap.

**What works today (through PR 6):**

- Open and view PDFs, with pan, scroll, and Acrobat-style zoom (fit page, fit width, actual size, custom %)
- Two view modes: single page (one page at a time) and continuous (vertical scroll through every page)
- Page navigation: prev/next/first/last, go-to-page dialog, full keyboard shortcut surface
- Thumbnail sidebar and outline (TOC) sidebar — dockable, tabified on the left, toggle via the View menu
- In-document text search (case-insensitive substring) with yellow/orange highlight overlays and Acrobat-style wrap; highlights span every visible page in continuous mode and scroll the current hit into view
- Full-screen mode (F11) that hides menubar, toolbars, status bar, and docks while keeping all shortcuts live
- Manual dark mode toggle, persisted across sessions
- File → Open Recent submenu (last 10 documents) and a remembered last-used Open directory
- Multi-document tabs: open many PDFs at once, switch with Ctrl+PgUp/PgDown, close with Ctrl+W
- Cross-PDF search ("All open documents" scope): a right-side results panel groups matches by document; F3/Shift+F3 walk the flat result list across docs and auto-switch tabs at boundaries
- Project-relative logging when running from source; OS-standard app-data location when packaged

**Coming next:** Milestone 2 begins with PR 7 — text selection, copy, and extraction of text and images.

## Scope

**In scope for v1:**

- Reader: rendering, navigation, zoom, view modes, thumbnails, outline, text search, multi-document tabs, full-screen, dark mode, recent files
- Text & image extraction
- Page operations: rotate, delete, insert, reorder, crop, extract, split, merge, duplicate
- Security: password protection, permissions, metadata sanitization, redaction
- OCR for scanned PDFs (Tesseract)
- Visual diff between two PDFs
- Optimization: compression, linearization
- Combine PDFs, images, and text files into one PDF

**Out of scope for v1:**

Annotations, forms, digital signatures, in-place text editing, PDF/A conversion, Office-document combine, HEIC image support.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/) for dependency management
- Tesseract (only needed once OCR ships in PR 12)

## Development setup

```bash
git clone https://github.com/deswhk/pdfprism.git
cd pdfprism
uv sync --all-extras
uv run pre-commit install
uv run pytest
```

`pre-commit install` activates both the `pre-commit` (file hygiene + ruff + gitleaks) and `pre-push` (block direct pushes to `main`) hooks because `default_install_hook_types: [pre-commit, pre-push]` is set in `.pre-commit-config.yaml`.

## Usage

```bash
uv run pdfprism
```

Then `File > Open` (Ctrl+O) to choose a PDF, or pick one from `File > Open Recent`. Use the menus, toolbar, sidebars, and keyboard shortcuts to navigate, zoom, switch view modes, search, and toggle dark mode or full-screen.

### Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open | Ctrl+O |
| Close tab | Ctrl+W |
| Previous tab | Ctrl+PgUp |
| Next tab | Ctrl+PgDown |
| Quit | Ctrl+Q |
| Find | Ctrl+F |
| Find next | F3 |
| Find previous | Shift+F3 |
| Previous page | PgUp |
| Next page | PgDown |
| First page | Ctrl+Home |
| Last page | Ctrl+End |
| Go to page | Ctrl+G |
| Single-page view | Ctrl+3 |
| Continuous view | Ctrl+4 |
| Fit page | Ctrl+0 |
| Fit width | Ctrl+1 |
| Actual size (100%) | Ctrl+2 |
| Zoom in | Ctrl+= or Ctrl++ |
| Zoom out | Ctrl+- |
| Toggle thumbnails sidebar | F4 |
| Toggle outline sidebar | F5 |
| Toggle full-screen | F11 |
| Exit full-screen | Esc |
| Ctrl + mouse wheel | Zoom |
| Click and drag | Pan |

Logs are written to `<project>/logs/pdfprism.log` when running from source, or to the OS-standard app-data location when running from a packaged install.

## Stack

- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF engine
- [PySide6](https://doc.qt.io/qtforpython-6/) — UI framework
- [Tesseract](https://tesseract-ocr.github.io/) — OCR (via PyMuPDF integration)
- [uv](https://docs.astral.sh/uv/) — packaging
- pytest, ruff, mypy, pre-commit — quality

## Architecture

For the design rationale, layered architecture, the `DocumentAdapter` Protocol, the test strategy, the full roadmap, and what is intentionally deferred, see [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

## License

[AGPL-3.0](./LICENSE). This project depends on PyMuPDF, which is AGPL, so derivative works must also be AGPL.
