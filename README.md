# pdfprism

A PDF reader and editor built on PyMuPDF and PySide6.

A prism decomposes light into its components; pdfprism decomposes PDFs into theirs — pages, text, images, metadata — and gives you the tools to read them, restructure them, secure them, and put them back together.

## Status

Under active development. Milestone 1 (Reader Core) is the current focus; see [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) for the full 15-PR roadmap.

**What works today (through PR 4):**

- Open and view PDFs, with pan, scroll, and Acrobat-style zoom (fit page, fit width, actual size, custom %)
- Page navigation: prev/next/first/last, go-to-page dialog, full keyboard shortcut surface
- Thumbnail sidebar and outline (TOC) sidebar — dockable, tabified on the left, toggle via the View menu
- In-document text search (case-insensitive substring) with yellow/orange highlight overlays and Acrobat-style wrap
- Project-relative logging when running from source; OS-standard app-data location when packaged

**Coming next (Milestone 1):** continuous and two-up view modes, full-screen, dark mode, recent files, multi-document tabs, and search across multiple PDFs.

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

Then `File > Open` (Ctrl+O) to choose a PDF. Use the menus, toolbar, sidebars, and keyboard shortcuts to navigate, zoom, and search.

### Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open | Ctrl+O |
| Close document | Ctrl+W |
| Quit | Ctrl+Q |
| Find | Ctrl+F |
| Find next | F3 |
| Find previous | Shift+F3 |
| Previous page | PgUp |
| Next page | PgDown |
| First page | Ctrl+Home |
| Last page | Ctrl+End |
| Go to page | Ctrl+G |
| Fit page | Ctrl+0 |
| Fit width | Ctrl+1 |
| Actual size (100%) | Ctrl+2 |
| Zoom in | Ctrl+= or Ctrl++ |
| Zoom out | Ctrl+- |
| Toggle thumbnails sidebar | F4 |
| Toggle outline sidebar | F5 |
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
