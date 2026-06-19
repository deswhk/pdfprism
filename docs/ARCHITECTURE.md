# pdfprism Architecture

This document describes the architecture, design principles, and roadmap of
pdfprism. It is the single source of truth for "why is the code this shape" —
read it before making structural changes.

## Overview

pdfprism is a desktop PDF reader and editor built on PyMuPDF (the PDF engine)
and PySide6 (the UI framework). It targets the working set of features real
users actually use 90% of the time: read, navigate, search, restructure pages,
secure, OCR, optimize. It does not (and intentionally will not, in v1) support
content editing of text and images, annotations, forms, digital signatures, or
PDF/A conversion.

## Design Principles

**Design before code.** Trade-offs are worked through explicitly in writing
before committing to a structure. API choices, library selections, and
architectural patterns are researched and justified, not assumed.

**Layered architecture with one engine seam.** The codebase is divided into
three layers: `core` (domain model and adapter contract), `services`
(pure-logic operations on documents), and `ui` (Qt widgets and windows). The
PDF engine (PyMuPDF) is hidden behind a single Protocol in
`core/document.py`. Services and UI talk to PDFs exclusively through that
Protocol, so if PyMuPDF is ever swapped for a permissively-licensed alternative
(e.g., pikepdf + pypdfium2), the rewrite is confined to `core/adapters/`.

**Services know nothing about the UI.** Every operation that does something to
a document lives in `services/`, takes inputs, returns outputs, and raises
typed exceptions. Services are unit-testable without a Qt event loop and
without mocking.

**UI knows nothing about the engine.** Qt widgets call services and the
adapter Protocol. They never `import pymupdf`.

**Transformations return new documents.** Page operations (split, merge,
rotate, etc.) produce new outputs rather than mutating in place. Easier to
reason about, easier to undo, easier to test.

**Long-running operations run on a worker thread.** OCR, compression, visual
diff, and search-across-multiple-PDFs are all CPU-bound and can take seconds
to minutes. They run on a `QThread` worker with progress reporting back to
the main thread; the UI never blocks.

**Real PDFs, not mocks.** PDFs are too quirky and engine-specific for mocks
to be trustworthy. Tests use real PDF fixtures generated deterministically
by `scripts/generate_sample_pdf.py`.

**Standard `logging`, no wrapper.** The stdlib `logging` module everywhere,
configured once at startup in `pdfprism.logging_config.configure()`. Each
module gets its own logger via `logger = logging.getLogger(__name__)`.

**AGPL-3.0 because of PyMuPDF.** This is a non-negotiable downstream of the
engine choice. If the project ever needs a more permissive license, the
engine swap (see above) is the first step.

## Layered Structure

```
src/pdfprism/
├── core/                        # Domain layer
│   ├── types.py                 # PageInfo, DocumentInfo (frozen dataclasses)
│   ├── exceptions.py            # PdfPrismError + specific subclasses
│   ├── document.py              # DocumentAdapter Protocol
│   └── adapters/
│       └── pymupdf_adapter.py   # Concrete PyMuPDF implementation
├── services/                    # Pure-logic operations (added per PR)
│   ├── pages.py                 # PR 8: rotate, delete, insert, reorder, etc.
│   ├── security.py              # PR 10: password, permissions, sanitize
│   ├── redaction.py             # PR 11: true content removal
│   ├── ocr.py                   # PR 12: Tesseract pipeline
│   ├── search.py                # PR 4, 6: single & multi-doc
│   ├── extract.py               # PR 7: text, images
│   ├── compare.py               # PR 15: visual diff
│   ├── optimize.py              # PR 13: compress, linearize
│   └── combine.py               # PR 14: PDFs + images + .txt
├── ui/                          # Qt widgets and windows
│   ├── main_window.py           # PR 1 minimum; expands per PR
│   ├── widgets/                 # PR 3+: page_view, thumbnail_panel, etc.
│   └── dialogs/                 # PR 9+: password, merge, ocr, etc.
├── config.py                    # App constants (name, org, etc.)
├── logging_config.py            # Stdlib logging setup
└── app.py                       # Entry point
```

## The DocumentAdapter Protocol

`pdfprism.core.document.DocumentAdapter` defines what a PDF engine must
provide:

- `open(path, password=None)` — load a PDF
- `close()` — release engine resources (idempotent)
- `page_count` property
- `get_document_info()` — metadata
- `get_page_info(index)` — per-page metadata
- `render_page(index, zoom=1.0)` — PNG bytes

The protocol uses `@runtime_checkable` so it can be verified at runtime with
`isinstance`. Each new adapter must satisfy this contract and pass an
equivalent test suite. Adapters are stateful: a single instance holds at most
one open document. Opening a second document on the same instance closes the
first.

## Error Handling

All errors raised by the core layer inherit from `PdfPrismError`:

- `PdfPrismError`
  - `DocumentOpenError` — file not found, invalid PDF, or open failure
    - `PasswordRequiredError` — encrypted PDF, no/wrong password
  - `PageOutOfRangeError` — page index outside `[0, page_count)`

Services and UI catch the broad `PdfPrismError` for display and the specific
subclasses for behaviour (e.g., showing a password prompt on
`PasswordRequiredError`). Engine-specific exceptions never escape the
adapter.

## Logging

`pdfprism.logging_config.configure(log_dir)` sets up two handlers:

- Rotating file handler at `<log_dir>/pdfprism.log` (10 MB per file, 5
  backups, UTF-8).
- Console handler to stderr.

`log_dir` is resolved by `app._resolve_log_dir()`:

- If a `pyproject.toml` is findable by walking up from `app.py` (running
  from source), logs go to `<project_root>/logs/`.
- Otherwise (packaged install), logs go to the OS-standard app data location
  via `QStandardPaths.AppDataLocation`.

Every module does `logger = logging.getLogger(__name__)`; the module path
becomes the logger name.

## Testing Strategy

- **Real PDF fixtures.** `scripts/generate_sample_pdf.py` produces
  `tests/fixtures/sample.pdf` with known content, metadata, and dimensions.
  Tests assert exact values.
- **Adapter contract tests.** `tests/core/test_pymupdf_adapter.py` covers
  Protocol conformance, every method, and edge cases (missing file, garbage
  file, out-of-range pages, idempotent close).
- **pytest fixtures for composition.** `conftest.py` provides
  `sample_pdf_path`, `garbage_file`, `missing_pdf_path`; the test file layers
  `adapter` and `opened_adapter` on top.
- **UI tests** (later PRs) will use `pytest-qt` for smoke tests: instantiate
  widgets, trigger signals, verify state — no full event-loop driving unless
  necessary.

## Roadmap

Fifteen PRs across five milestones. Each PR is a self-contained branch that
merges via PR review and CI on green.

### Milestone 1 — Reader Core

- **PR 1: Foundation.** Scaffold, license, CI, branch protection (via
  pre-commit hook), `DocumentAdapter` Protocol, `PyMuPDFAdapter`, minimal Qt
  window that opens a PDF and renders page 1.
- PR 2: Navigation, zoom, single-page view.
- PR 3: Thumbnails sidebar, outline (TOC) sidebar.
- PR 4: In-document text search.
- PR 5: Continuous / two-up view modes, full-screen, dark mode, recent files.
- PR 6: Multi-document tabs, search across multiple PDFs.

### Milestone 2 — Extraction

- PR 7: Text selection & copy, extract text/images to disk.

### Milestone 3 — Page Operations

- PR 8: `services/pages.py` — rotate, delete, insert, reorder, crop, extract,
  split, merge, duplicate.
- PR 9: "Organize Pages" UI.

### Milestone 4 — Security & OCR

- PR 10: Password protect, permissions, metadata sanitization.
- PR 11: Redaction (separate PR because correctness is critical).
- PR 12: OCR via Tesseract.

### Milestone 5 — Advanced

- PR 13: Compression and linearization.
- PR 14: Combine PDFs + images + .txt into one PDF.
- PR 15: Visual diff between two PDFs.

## Intentionally Out of Scope (v1)

- **In-place text editing.** PDF text is positioned glyphs, not flowing text.
  Doable but very hard.
- **Annotations** (highlights, sticky notes, drawings, stamps).
- **Form creation and form-field editing.** Form *filling* may be considered
  later.
- **Digital signatures.** Sign and verify.
- **PDF/A conversion.**
- **Office docs in "Combine"** (`.docx`, `.xlsx`, `.pptx`). Would require
  LibreOffice headless. May be added later as an optional feature.
- **HEIC images** in "Combine".

These are out of scope because of complexity, dependency weight, or secondary
value relative to the core reader. The architecture does not preclude them;
they are simply not on the v1 path.

## Glossary

- **Adapter.** The concrete implementation of `DocumentAdapter` for a
  particular PDF engine.
- **AGPL.** GNU Affero General Public License v3.0. The license we use,
  inherited from PyMuPDF.
- **AcroForm.** Adobe's interactive PDF form format. Filling AcroForms is a
  deferred consideration.
- **PDF/A.** Archival PDF format. Out of scope for v1.
- **PDFium.** Google's PDF rendering engine, used by Chrome and available
  via the `pypdfium2` Python binding. The most likely replacement for
  PyMuPDF if licensing intent ever shifts.
- **Protocol** (Python). PEP 544 structural subtyping. Used here as the
  interface for `DocumentAdapter`.
- **Redaction.** Removing sensitive content from a PDF such that it cannot
  be recovered (not merely covering it visually).
- **XFA.** Legacy Adobe XML Forms Architecture. Deferred indefinitely.

## Suggested Reading Order

If you are new to the codebase, read in this order:

1. `pyproject.toml` — what we depend on and how the project is built.
2. `src/pdfprism/core/types.py` — the data shapes services and UI pass
   around.
3. `src/pdfprism/core/exceptions.py` — the error vocabulary.
4. `src/pdfprism/core/document.py` — the engine seam (read the docstrings).
5. `src/pdfprism/core/adapters/pymupdf_adapter.py` — the only file that
   knows what PyMuPDF looks like.
6. `src/pdfprism/ui/main_window.py` — the current UI surface (minimal in
   PR 1).
7. `src/pdfprism/app.py` — entry point and how everything wires together.
8. `tests/core/test_pymupdf_adapter.py` — the contract, expressed as
   assertions.

When adding a new feature, work bottom-up: extend the Protocol if needed,
implement in the adapter, add or extend a service, then wire it into the UI.
