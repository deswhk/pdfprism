# pdfprism

A PDF reader and editor built on PyMuPDF and PySide6.

A prism decomposes light into its components; pdfprism decomposes PDFs into theirs — pages, text, images, metadata — and gives you the tools to read them, restructure them, secure them, and put them back together.

## Status

**PR 1 — Foundation** complete. The app launches, opens a PDF via `File > Open` (Ctrl+O), and renders page 1. Subsequent PRs add navigation, zoom, thumbnails, outline, search, page operations, security, OCR, and more. See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) for the full roadmap.

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
- Tesseract (needed only when OCR ships in PR 12)

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

Then `File > Open` (Ctrl+O) to choose a PDF. PR 1 renders page 1; future PRs add the rest of the reader feature set.

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
