# pdfprism

A PDF reader and editor built on PyMuPDF and PySide6.

A prism decomposes light into its components; pdfprism decomposes PDFs into theirs — pages, text, images, metadata — and gives you the tools to read them, restructure them, secure them, and put them back together.

## Status

Under active development. Milestones 1–3 and PR 10, PR 10.5, PR 11, PR 12 (plus PR 12.1, 12.2, 12.3) shipped; PR 13 (OCR) is next and closes Milestone 4. See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) for the full roadmap.

**What works today (through PR 12):**

- Open and view PDFs, with pan, scroll, and Acrobat-style zoom (fit page, fit width, actual size, custom %)
- Two view modes: single page (one page at a time) and continuous (vertical scroll through every page)
- Page navigation: prev/next/first/last, go-to-page dialog, full keyboard shortcut surface
- Thumbnail sidebar and outline (TOC) sidebar — dockable, tabified on the left, toggle via the View menu
- In-document text search with case-sensitive (`Aa`) and whole-word (`[w]`) toggle buttons, yellow/orange highlight overlays, and Acrobat-style wrap; highlights span every visible page in continuous mode and scroll the current hit into view; search hits on rotated pages now project through the page rotation so the overlay tracks the displayed text
- Full-screen mode (F11) that hides menubar, toolbars, status bar, and docks while keeping all shortcuts live
- Manual dark mode toggle, persisted across sessions
- File → Open Recent submenu (last 10 documents) and a remembered last-used Open directory
- Multi-document tabs: open many PDFs at once, switch with Ctrl+PgUp/PgDown, close with Ctrl+W
- Cross-PDF search ("All open documents" scope): a right-side results panel groups matches by document; F3/Shift+F3 walk the flat result list across docs and auto-switch tabs at boundaries
- Project-relative logging when running from source; OS-standard app-data location when packaged
- Text selection with a Hand/Select tool toggle (H / V), drag-rect word selection with blue translucent highlight, Ctrl+C copy, and a right-click context menu for Copy or Extract Selection to File
- File → Extract menu for whole-document Text and Images extraction, with a page-range dialog; per-hit context snippets now show beside each result in the cross-document search panel
- Page operations on the current page: rotate (Ctrl+R / Ctrl+Shift+R / 180°), delete (with confirmation), insert blank page after, duplicate, move (Ctrl+Shift+M), and crop (margin dialog in PDF points)
- Encrypted PDFs: opening password-protected files prompts for the password with an inline retry loop (wrong password shows an error banner, unlimited retries, Cancel gives up cleanly). No password caching; re-opens from Recent Files prompt again. Set, change, or remove the password on any open document via File → Security → Password... -- destructive Remove branch is guarded by a confirmation prompt.
- View and edit document metadata via File → Properties.... Six standard Info dict fields (title, author, subject, keywords, creator, producer) are editable. A one-click **Sanitize All Fields** button clears every field for the user who wants to share a document without personally identifying info; a checkbox controls whether the XMP metadata stream is also removed (defaults to on).
- Redact regions of a page: press R (or View → Redaction Mode), drag rectangles over content to mark it, review the pending marks, then Redaction → Apply Redactions... to permanently destroy the underlying content. Or, in Select mode (V), right-click selected text and choose Redact Selection to redact per-word (one mark per selected word, tight rects that avoid whitespace and multi-column artifacts). Marks are non-destructive until applied. When you Apply Redactions, choose "Apply and Save As..." to protect the original by writing the destructive result to a new file, or "Apply to Original" to commit in place. Saving preserves pending marks for later review. Right-click on any pending mark and pick "Remove This Mark" to delete just that one. Redaction → Clear All Pending removes every mark without applying (nuclear option). For bulk redaction across the document (e.g. every occurrence of a phone number or a name), use Redaction → Search and Redact... -- run a search with case-sensitive and whole-word options, then tick which matches to redact from the results list. Customize redaction defaults via Redaction → Options...: fill color, replacement text (e.g. "[REDACTED]"), and how apply handles overlapping images / graphics / text. Settings persist across sessions.
- Save (Ctrl+S) writes mutations in place; Save As (Ctrl+Shift+S) writes to a new path. Modified tabs show ` *` in the tab title; closing a modified tab prompts Save / Discard / Cancel
- Edit menu reorganized: Find actions stay at the top; new Edit → Page submenu groups all page operations
- Cross-document page operations via the new File → Pages submenu: Extract Pages to File (save a page range as a new PDF), Insert Pages from File (insert a range from another PDF at a chosen position), Split Document (every N pages or at specified page boundaries, with zero-padded output names), and Merge Documents (pick from open tabs with reorder, opens the result as a new tab)
- Organize Pages panel (View → Toggle Organize Pages or F6): dockable grid view of all pages with multi-select (Ctrl/Shift), drag-to-reorder, and selection-aware operations (Rotate Right/Left/180°, Delete, Duplicate, Crop Selection, Extract Selection to File) via toolbar, context menu, or keyboard shortcuts (Ctrl+R, Delete, Ctrl+D, Ctrl+A, Ctrl+E). The Crop dialog now includes a live rendered preview of the page with the crop rectangle drawn over it, updating as you type. Hidden by default; persisted across sessions.

**Coming next:** Milestone 4 wraps up with PR 13 (OCR via Tesseract). PR 11.5 (permissions dialog with owner/user password distinction) and PR 12.1-12.3 (text-selection redact, search-redact, redaction options) are deferred pending concrete user demand.

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
| Save | Ctrl+S |
| Save As | Ctrl+Shift+S |
| Rotate page right | Ctrl+R |
| Rotate page left | Ctrl+Shift+R |
| Move page | Ctrl+Shift+M |
| Copy selected text | Ctrl+C |
| Hand tool (pan) | H |
| Select Text tool | V |
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
| Click and drag | Pan (Hand tool) / Select text (Select tool) |

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

[AGPL-3.0](./LICENSE). This project depends on [PyMuPDF](https://github.com/pymupdf/PyMuPDF) which is AGPL-licensed, so derivative works must also be AGPL. (PyMuPDF is dual-licensed by Artifex Software; commercial licensing is available separately if you need to distribute under different terms.) See [`NOTICE.txt`](./NOTICE.txt) for full third-party notices and the warranty disclaimer.
