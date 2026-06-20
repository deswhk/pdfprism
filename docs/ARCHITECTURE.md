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

**User-facing state persists via `QSettings`.** View preferences (dark mode),
recent files, and the last-used Open directory are stored under the
`pdfprism` organization / application keys via `QSettings`. The platform
decides the backend (registry on Windows, plist on macOS, INI on Linux);
the code only cares about the key names.

**AGPL-3.0 because of PyMuPDF.** This is a non-negotiable downstream of the
engine choice. If the project ever needs a more permissive license, the
engine swap (see above) is the first step.

## Layered Structure

```text
src/pdfprism/
├── core/                        # Domain layer
│   ├── types.py                 # PageInfo, DocumentInfo, OutlineItem, SearchHit
│   ├── exceptions.py            # PdfPrismError + specific subclasses
│   ├── document.py              # DocumentAdapter Protocol
│   └── adapters/
│       └── pymupdf_adapter.py   # Concrete PyMuPDF implementation
├── services/                    # Pure-logic operations on documents
│   ├── search.py                # PR 4: document-wide text search
│   ├── pages.py                 # PR 8: rotate, delete, insert, reorder, etc.
│   ├── security.py              # PR 10: password, permissions, sanitize
│   ├── redaction.py             # PR 11: true content removal
│   ├── ocr.py                   # PR 12: Tesseract pipeline
│   ├── extract.py               # PR 7: text, images
│   ├── compare.py               # PR 15: visual diff
│   ├── optimize.py              # PR 13: compress, linearize
│   └── combine.py               # PR 14: PDFs + images + .txt
├── ui/                          # Qt widgets and windows
│   ├── main_window.py           # Menus, toolbar, search toolbar, status bar, docks
│   ├── theme.py                 # PR 5: DARK_QSS stylesheet
│   ├── page_cache.py            # Thread-safe LRU pixmap cache (shared)
│   ├── widgets/
│   │   ├── page_view.py         # QGraphicsView page surface + view modes + highlight overlay
│   │   ├── search_bar.py        # Find input + Prev/Next + counter
│   │   ├── thumbnail_panel.py   # QListView thumbnail strip
│   │   └── outline_panel.py     # QTreeView outline (TOC)
│   └── dialogs/                 # goto_page; password (PR 10+), merge (PR 9+)
├── config.py                    # App constants (name, org, MAX_RECENT_FILES, etc.)
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
- `get_outline()` — flat `list[OutlineItem]` in document order; empty if none
- `search_page(index, term)` — flat `list[SearchHit]` for the given page;
  case-insensitive for ASCII; empty list if no matches or empty term

The protocol uses `@runtime_checkable` so it can be verified at runtime with
`isinstance`. Each new adapter must satisfy this contract and pass an
equivalent test suite. Adapters are stateful: a single instance holds at most
one open document. Opening a second document on the same instance closes the
first.

The outline is returned as a flat list with hierarchy expressed through
`OutlineItem.level` (1 = top-level chapter, 2 = child of the most recent
level-1 entry, etc.). This matches PyMuPDF's `Document.get_toc()` shape and
is what `OutlinePanel` converts into a tree. Page numbers are normalized to
0-based here at the adapter boundary, never further up. Search hit
coordinates are in PDF page space (1 unit = 1/72 inch, origin top-left) —
the same coordinate system as `render_page`'s output.

## The PageView Widget

`pdfprism.ui.widgets.page_view.PageView` is the central viewing surface for
PDF pages. It subclasses `QGraphicsView` and holds:

- The shared `PageCache`
- Page count, current page index (0-based)
- Current zoom mode (`FIT_PAGE`, `FIT_WIDTH`, `ACTUAL_SIZE`, or `CUSTOM`)
- Custom zoom ratio (Acrobat-style; 1.0 = 100%)
- Current view mode (`SINGLE_PAGE` or `CONTINUOUS`) — see "View Modes" below
- Search state: list of `SearchHit`s and a pointer to the "current" one

It does **not** hold the adapter directly — the cache does. `set_adapter`
forwards to the cache and captures `page_count` locally.

**Rendering strategy.** Each page is rendered by the cache once at a fixed
oversample factor (`_RENDER_SCALE = 2.0`, i.e. `zoom=2.0` passed to the
adapter via `PageCache.get_or_render`) and displayed via `QGraphicsView`'s
transform for the actual visible zoom. This avoids a full re-render on every
zoom step. At extreme zoom (above ~200%) the displayed pixels are
interpolated; a future PR can re-render at higher DPI past a threshold if
quality becomes an issue.

**Effective zoom math.** "Acrobat-style" zoom (1.0 = page rendered at 72
DPI on screen) maps to `self.transform().m11() * _RENDER_SCALE`. The widget
emits `zoom_changed(float)` with this value; the main window's status bar
displays it as a percentage.

**Signals.**

- `page_changed(int)` — emitted when the displayed page index changes
- `zoom_changed(float)` — emitted when the effective zoom changes
- `view_mode_changed(ViewMode)` — emitted when the layout switches between
  single-page and continuous

## View Modes

`PageView` supports two layouts, controlled by the `ViewMode` enum
(`SINGLE_PAGE`, `CONTINUOUS`) and selected via `View → Single Page` (Ctrl+3)
or `View → Continuous` (Ctrl+4). The two actions live in a `QActionGroup`
with `setExclusive(True)` so the menu always shows exactly one checked.

**Single-page mode** shows exactly one `QGraphicsPixmapItem` at the scene
origin. Navigation replaces the item with the requested page; zoom is the
view's transform on that single item. This is the default and the lightest
weight option.

**Continuous mode** lays out every page as its own `QGraphicsPixmapItem`
stacked vertically with a fixed gutter. Per-page rect Y offsets are
precomputed when the layout is built and used by `_on_scroll` to update
`current_page` as the user scrolls past page boundaries (the topmost
visible page wins). Navigation via `go_to_page` scrolls to the
corresponding page rect rather than swapping items. Highlights are drawn
on top of every visible page that has hits, so search overlays span the
document instead of being clipped to a single page; the
`_ensure_hit_visible` helper additionally scrolls the current hit into
the viewport in continuous mode, so F3 across pages always lands the
match somewhere the user can see.

A `view_mode_changed(ViewMode)` signal fires whenever the mode actually
changes (no-op `set_view_mode` calls are filtered). MainWindow listens
on this signal to keep the View menu's `QActionGroup` checkmark in sync
even if the mode is set programmatically — closing the loop between
the menu and the underlying state.

**Known limitation.** Continuous mode renders all pages eagerly when the
mode is entered or the document is bound. This is fine for the test
fixture (3 pages) and modest documents; very large documents (hundreds
of pages) will pay the full render cost upfront. Lazy on-scroll
rendering, and a two-up "facing pages" layout, are tracked as PR 5.5
candidates.

## PageCache

`pdfprism.ui.page_cache.PageCache` is a thread-safe LRU cache of rendered
page pixmaps, keyed by `(page_index, zoom)`. Both `PageView` and
`ThumbnailPanel` are constructed with a shared `PageCache` instance owned
by the main window.

**Why this exists.** It centralizes the "render a page" call: only the cache
knows about the adapter, only the cache knows how to convert PNG bytes to
`QPixmap`. Consumers ask for `get_or_render(page_index, zoom)` and don't
care whether the result was rendered or replayed. Cross-consumer reuse
happens only when both consumers ask at the same zoom — in practice
`PageView` uses 2.0 and `ThumbnailPanel` uses 0.25, so the bigger win is
intra-consumer (repeat visits to the same page, scrollback through
thumbnails) rather than cross-consumer sharing.

**Rebinding.** `set_adapter(adapter)` clears the cache and binds a new
adapter. `set_adapter(None)` unbinds and clears. Both `PageView` and
`ThumbnailPanel` call this when their own `set_adapter` is invoked; the
duplication is intentional — either widget can be driven independently in
tests without relying on the other to seed the cache.

**Eviction.** Default max 64 entries. LRU by access — both `get()` and
`get_or_render()` promote the entry on hit.

**Concurrency.** A `threading.Lock` guards all reads and writes. Future
async rendering (a PR 3.5 candidate if real-world docs prove laggy) can
submit work from a worker thread without further coordination.

**Placeholder behavior.** If `get_or_render` is called with no adapter
bound, it returns an empty `QPixmap`. Consumers treat that as "show
nothing" — `QGraphicsView` displays an empty scene, `QListView` displays
a blank icon.

## Thumbnails and Outline Sidebars

Two dockable panels share the left side of the main window, tabified with
thumbnails up front by default. `View → Thumbnails` (F4) and
`View → Outline` (F5) toggle each via Qt's built-in
`QDockWidget.toggleViewAction()`.

`ThumbnailPanel` (`QListView` + `ThumbnailModel`) shows one small pixmap
per page, rendered through the shared `PageCache` at zoom 0.25.
`IconMode + Flow.TopToBottom + no-wrap` gives the Acrobat-style vertical
strip; `IconSize` is capped at 160×220 so landscape pages are scaled to
fit while portrait pages display close to native at the chosen zoom. The
model is deliberately thin: `set_adapter` resets row count to
`adapter.page_count` (or 0), and `data()` returns a label for
`DisplayRole` and a cache-rendered pixmap for `DecorationRole`. Rendering
is synchronous on demand — fine for the 3-page test fixture and most
real-world docs. A PR 3.5 candidate adds a worker thread if scrolling
proves laggy on large docs.

`OutlinePanel` (`QTreeView` + `OutlineModel`) renders the document's
outline. The adapter returns a flat `list[OutlineItem]` in document order;
the model converts that to a tree via a stack-based pass: for each item,
pop nodes whose level is at or above the item's level until the stack top
is a strict ancestor, then attach. Each `OutlineNode` carries a back-pointer
to its parent so `QAbstractItemModel.parent()` can navigate up, and stores
its target `page_index` so a click can emit `page_selected(int)` without
re-walking the tree. The tree starts fully expanded.

**Signal wiring (MainWindow).**

- `thumbnail_panel.page_selected → page_view.go_to_page`
- `outline_panel.page_selected → page_view.go_to_page`
- `page_view.page_changed → thumbnail_panel.set_current_page`

There is intentionally no back-connect from `PageView` to `OutlinePanel`:
multiple outline entries can target the same page, so there is no canonical
"current outline item" to highlight.

## Text Search

In-document text search lives across three pieces: `services/search.py`
(the document-wide aggregator), `ui/widgets/search_bar.py` (the input UI),
and `PageView`'s highlight overlay (visual feedback). MainWindow owns the
search cursor state and wires the three together.

`SearchService.find_all(term)` walks the document via the adapter and
returns a flat list of `SearchHit`s in page order. The service is thin
today because the adapter's `search_page` already does the per-page work;
the layer exists because the planned PR 4.5 adds case-sensitive and
whole-word matching by extracting `page.get_text("words")` and filtering
rect-by-rect, which is a service concern (operates above the adapter's
native call) not an adapter concern.

`SearchBar` (`QLineEdit` + Prev/Next buttons + match counter + close
button) is a pure UI shell: it emits `find_requested(str)` on Enter (with
whitespace stripped), `next_requested` and `prev_requested` on its
buttons, and `closed` on the X button or Escape (caught via an event
filter on the input so it works even when the input has focus). It does
not know about the document or the service.

`PageView` exposes `set_search_hits(list[SearchHit])`, `set_current_hit(
SearchHit | None)`, and `clear_search()`. The hits are stashed in state;
when the view renders any page, it filters hits to that page and draws
each as a translucent `QGraphicsRectItem` on the scene at z-value 1
(above the cached pixmap). Yellow for non-current hits, orange for the
one `set_current_hit` points to. Because the highlights are scene
overlays rather than baked into the pixmap, the `PageCache` is never
invalidated by search, and the existing zoom transform scales highlights
along with the page. In continuous mode the same machinery draws
overlays on every visible page that has hits, and `_ensure_hit_visible`
scrolls the current hit into the viewport so F3 across pages always
lands somewhere visible.

**Signal wiring (MainWindow).**

- `search_bar.find_requested(term) → _on_find`: runs the service, stashes
  results, points the cursor at hit 0, calls `page_view.set_current_hit`,
  updates the counter.
- `search_bar.next_requested / prev_requested → _on_find_next /
  _on_find_prev`: advance the cursor with Python `%` modulo for
  Acrobat-style wrap, then `_update_current_hit`.
- `search_bar.closed → _on_close_search`: clears state and hides the
  toolbar.

**Shortcuts** come from `QKeySequence.StandardKey`: `Ctrl+F` (Find),
`F3` (FindNext), `Shift+F3` (FindPrevious) on Windows/Linux, with the Mac
equivalents free if we ever ship there.

**Known limitation.** PyMuPDF's `Page.search_for` returns rects in
*unrotated* page coordinates. On pages with non-zero rotation (page 3 of
the test fixture is rotated 90°), the highlight overlays will be
misaligned with the rendered text. The fix is to pass `quads=True` and
project the resulting `Quad` objects through the page's rotation
transform. Tracked as a PR 4.5 candidate alongside case-sensitive and
whole-word matching, since all three need above-adapter manipulation of
PyMuPDF text data.

## Theme

`pdfprism.ui.theme.DARK_QSS` is a Qt Style Sheet (QSS) string applied
app-wide when dark mode is enabled. It covers `QMainWindow`, `QMenuBar`,
`QMenu`, `QToolBar`, `QToolButton`, `QStatusBar`, `QDockWidget`,
`QListView`, `QTreeView`, `QLineEdit`, `QPushButton`, `QScrollBar`, and
`QTabBar` — the surfaces the user actually sees. Backgrounds are
`#2b2b2b` / `#353535` / `#1e1e1e`, foreground is `#e0e0e0`, accent is
`#0078d4`.

`View → Dark Mode` is a checkable `QAction` whose state is persisted
under the QSettings key `view/dark_mode` and restored at startup. Toggling
it calls `QApplication.setStyleSheet(DARK_QSS)` to apply, or `""` to
revert to the platform default. The PDF page itself is rendered by
PyMuPDF and is unaffected by the stylesheet — only the chrome around it.

Light mode is the platform default style; there is intentionally no
custom light stylesheet, so the app respects platform conventions when
dark mode is off.

## Full Screen

`View → Full Screen` (F11) is a checkable `QAction` that toggles a
distraction-free presentation: menubar, both toolbars, status bar, and
both docks are hidden, and the window is switched to `showFullScreen`.
Before hiding, the previous visibility of each chrome element is snapped
into `_fullscreen_state`; toggling off (F11 again, or `Esc` via
`keyPressEvent`) restores each element to exactly the state the user had
before. There is no separate "presentation mode" — it is just full
screen with everything hidden.

All actions that have shortcuts are registered on `MainWindow` itself via
`addAction(...)` after construction. This is required because Qt only
delivers shortcut events through actions that live on a visible widget,
and the menubar is hidden in full-screen. Without registering on the
window, F11 / Ctrl+F / arrow keys etc. would stop working as soon as the
chrome disappeared.

## Recent Files and Last Directory

`File → Open Recent` is a submenu populated from QSettings key
`recent/files` (newline-joined list of paths, most recent first, capped
at `MAX_RECENT_FILES = 10` from `pdfprism.config`). Each entry's
`triggered` lambda calls `_open_path(p)` with the captured path, so
opening from history goes through the same code as a fresh open. A
`Clear Recent` action at the bottom of the submenu wipes the list.
Entries whose underlying file no longer exists are filtered out at
render time but kept in storage (the user can `Clear Recent` to prune
them).

`File → Open...` remembers the last successfully chosen directory via
QSettings key `recent/last_dir` and seeds the file dialog with it on
the next invocation. The Open dialog and Open Recent submenu are the
only two ways a user can pick a file path in the app today.

**`_on_open` vs `_open_path`.** The dialog flow (`_on_open`) is separated
from the work flow (`_open_path`) so the recent-files menu can invoke
the latter directly without round-tripping through the file picker.
`_open_path` canonicalizes the path with `Path.resolve(strict=False)`
(catching `OSError` and falling back to the original) so two different
spellings of the same file collapse to one recent-files entry.

**Failed-open recovery.** If `_open_path` catches `PdfPrismError`, it
calls `_reset_to_empty_state()` to clear all UI surfaces (page view,
sidebars, status bar, window title, action enablement) before showing
the error dialog. The adapter itself has already closed any
previously-open document by the time the exception is raised. The same
`_reset_to_empty_state` is shared by `File → Close`, which then also
calls `self._adapter.close()`.

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
  `tests/fixtures/sample.pdf` with known content, metadata, dimensions,
  and a four-entry outline (`Chapter 1: Introduction` with two nested
  subsections, then `Chapter 2: Conclusion`). Tests assert exact values.
- **Adapter contract tests.** `tests/core/test_pymupdf_adapter.py` covers
  Protocol conformance, every method, and edge cases (missing file,
  garbage file, out-of-range pages, idempotent close, outline parsing,
  case-insensitive search, empty term, missing term).
- **Service tests** (`tests/services/`) drive the service against a real
  adapter on the test fixture; they verify document-order and aggregation
  rather than mocking out the adapter.
- **UI widget tests** (`tests/ui/`) use `pytest-qt`'s `qtbot` fixture:
  instantiate the widget, drive its public API, assert state and emitted
  signals.
- **Autouse `qapp`.** `tests/ui/conftest.py` declares an autouse fixture
  that pulls in pytest-qt's `qapp`, so any test under `tests/ui/` can
  construct `QPixmap` and other `QPaintDevice` objects without crashing —
  `qtbot` alone covers tests that drive widgets, but `PageCache` tests
  don't need a widget and the cache still constructs `QPixmap` instances.
- **pytest fixtures for composition.** Top-level `conftest.py` provides
  `sample_pdf_path`, `garbage_file`, `missing_pdf_path`; per-test files
  layer `adapter`, `opened_adapter`, `page_view`, `panel`, `bar`,
  `service`, `adapter_with_doc`, and `sample_outline` on top.

## Roadmap

Fifteen PRs across five milestones. Each PR is a self-contained branch that
merges via PR review and CI on green.

### Milestone 1 — Reader Core

- **PR 1: Foundation.** Scaffold, license, CI, branch protection (via
  pre-commit hook), `DocumentAdapter` Protocol, `PyMuPDFAdapter`, minimal Qt
  window that opens a PDF and renders page 1.
- **PR 2: Navigation and zoom.** `PageView` widget (`QGraphicsView`-based);
  page navigation (prev / next / first / last / go-to); four zoom modes
  (fit page, fit width, actual size, custom %); View / Go menus, toolbar,
  status bar, full keyboard shortcut surface.
- **PR 3: Thumbnails and outline sidebars.** Shared `PageCache` (thread-safe
  LRU pixmap cache); `ThumbnailPanel` (`QListView` over the cache);
  `OutlinePanel` (`QTreeView` with a stack-built tree from the adapter's
  flat outline). Two tabified `QDockWidget`s on the left with View-menu
  toggles. `PageView` refactored to render through the shared cache;
  `DocumentAdapter` Protocol grew `get_outline()`.
- **PR 4: In-document text search.** `SearchHit` type, `search_page` on the
  Protocol, `SearchService` (services layer's first file). `SearchBar`
  widget in a togglable top toolbar (Ctrl+F / F3 / Shift+F3 with Acrobat
  wrap). `PageView` gained translucent overlay highlights (yellow others,
  orange current) drawn on the scene above the cached pixmap so search
  doesn't invalidate the cache. Case-insensitive substring only; case-
  sensitive, whole-word, regex, and rotated-page rect alignment deferred
  to PR 4.5.
- **PR 5: View modes, full-screen, dark mode, recent files.** `ViewMode`
  enum and a continuous-scroll layout in `PageView` (two-up "facing
  pages" deferred to PR 5.5); `view_mode_changed` signal closes the loop
  with the View menu's exclusive `QActionGroup`. F11 full-screen with
  state save / restore for menubar, toolbars, status bar, and docks; all
  shortcuts registered on `MainWindow` itself so they survive a hidden
  menubar. Manual dark mode toggle via the new `ui/theme.py` module
  (`DARK_QSS` app-wide stylesheet), persisted under QSettings
  `view/dark_mode`. `File → Open Recent` submenu and last-directory
  memory under QSettings `recent/files` and `recent/last_dir`; refactor
  of `_on_open` (dialog) vs `_open_path` (work, with
  `Path.resolve(strict=False)` canonicalization), plus a shared
  `_reset_to_empty_state` so failed opens leave the UI clean.
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
- **QSS.** Qt Style Sheet — Qt's CSS-like styling syntax. Used by the
  dark-mode theme.
- **Quad.** A general quadrilateral in PDF coordinates. PyMuPDF returns
  `Quad`s (rather than axis-aligned `Rect`s) when text is rotated, so the
  bounding region tracks the glyph orientation correctly.
- **Redaction.** Removing sensitive content from a PDF such that it cannot
  be recovered (not merely covering it visually).
- **TOC.** Table of Contents. Synonym for "outline" in PDF terminology.
- **XFA.** Legacy Adobe XML Forms Architecture. Deferred indefinitely.

## Suggested Reading Order

If you are new to the codebase, read in this order:

1. `pyproject.toml` — what we depend on and how the project is built.
2. `src/pdfprism/core/types.py` — the data shapes services and UI pass
   around (`PageInfo`, `DocumentInfo`, `OutlineItem`, `SearchHit`).
3. `src/pdfprism/core/exceptions.py` — the error vocabulary.
4. `src/pdfprism/core/document.py` — the engine seam (read the docstrings).
5. `src/pdfprism/core/adapters/pymupdf_adapter.py` — the only file that
   knows what PyMuPDF looks like.
6. `src/pdfprism/services/search.py` — the first service; the shape future
   services will follow.
7. `src/pdfprism/ui/page_cache.py` — the rendering choke point; everything
   that displays a page goes through here.
8. `src/pdfprism/ui/theme.py` — the dark-mode QSS stylesheet; small but
   referenced by `main_window.py`.
9. `src/pdfprism/ui/widgets/page_view.py` — the central page surface
   (zoom, navigation, view modes, signals, search highlights).
10. `src/pdfprism/ui/widgets/thumbnail_panel.py` — `QListView` thumbnails
    over the shared cache.
11. `src/pdfprism/ui/widgets/outline_panel.py` — `QTreeView` outline, with
    the stack-based flat-to-tree conversion.
12. `src/pdfprism/ui/widgets/search_bar.py` — find input, counter, signals.
13. `src/pdfprism/ui/main_window.py` — menus, toolbars, status bar, the two
    tabified left docks, the search toolbar, full-screen state, dark
    theme apply, and the recent-files / last-directory plumbing.
14. `src/pdfprism/app.py` — entry point and how everything wires together.
15. `tests/core/test_pymupdf_adapter.py` — the adapter contract, as
    assertions.
16. `tests/services/test_search.py` — service-level expectations.
17. `tests/ui/test_page_cache.py`, `test_page_view.py`,
    `test_thumbnail_panel.py`, `test_outline_panel.py`,
    `test_search_bar.py` — the UI surface, as assertions.

When adding a new feature, work bottom-up: extend the Protocol if needed,
implement in the adapter, add or extend a service, then wire it into the UI.
