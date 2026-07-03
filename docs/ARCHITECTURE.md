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

**Per-document state lives in `DocumentView`; `MainWindow` is a coordinator.**
Each open document gets its own adapter, page cache, page view, sidebars, and
search service, all owned by a `DocumentView` widget that is itself one tab in
the `QTabWidget` central. `MainWindow` holds chrome (menus, toolbars, status
bar, dock frames, results panel) and manages tab lifecycle, sidebar swapping,
cross-document search, and global state (full-screen, dark mode, recent files,
last-directory memory). This keeps per-tab state from leaking into MainWindow
and means closing a tab releases all of its engine resources and pixmap cache.

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
│   ├── types.py                 # PageInfo, DocumentInfo, OutlineItem, SearchHit, CrossDocHit
│   ├── exceptions.py            # PdfPrismError + specific subclasses
│   ├── document.py              # DocumentAdapter Protocol
│   └── adapters/
│       └── pymupdf_adapter.py   # Concrete PyMuPDF implementation
├── services/                    # Pure-logic operations on documents
│   ├── search.py                # PR 4/4.5/6: per-doc + cross-doc text search; SearchScope enum
│   ├── pages.py                 # PR 8: rotate, delete, insert, reorder, etc.
│   ├── security.py              # PR 10: password, permissions, sanitize
│   ├── redaction.py             # PR 11: true content removal
│   ├── ocr.py                   # PR 12: Tesseract pipeline
│   ├── extract.py               # PR 7: text + image extraction, snippet_around
│   ├── compare.py               # PR 15: visual diff
│   ├── optimize.py              # PR 13: compress, linearize
│   └── combine.py               # PR 14: PDFs + images + .txt
├── ui/                          # Qt widgets and windows
│   ├── main_window.py           # Tab management, dock frames, menus, toolbars, cross-search
│   ├── theme.py                 # PR 5: DARK_QSS stylesheet
│   ├── page_cache.py            # Thread-safe LRU pixmap cache (per-tab)
│   ├── widgets/
│   │   ├── document_view.py     # PR 6: one tab = one document; owns adapter, cache, views, sidebars, search
│   │   ├── page_view.py         # QGraphicsView page surface + view modes + highlight overlay
│   │   ├── search_bar.py        # Find input + scope dropdown + Prev/Next + counter
│   │   ├── search_results_panel.py  # PR 6: cross-doc search results tree
│   │   ├── thumbnail_panel.py   # QListView thumbnail strip
│   │   └── outline_panel.py     # QTreeView outline (TOC)
│   └── dialogs/                 # goto_page; extract (PR 7); crop (PR 8); extract_pages/insert_pages/split/merge (PR 8.5); password (PR 10+)
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

## Multi-document Tabs

Each open document lives in its own `DocumentView` widget; the central
widget of `MainWindow` is a `QStackedWidget` switching between an empty-state
placeholder and a `QTabWidget` of `DocumentView`s. `DocumentView` owns:

- a fresh `PyMuPDFAdapter` (so each tab opens its file independently)
- its own `PageCache` (per-tab bounded LRU; releases on tab close)
- a `PageView` (the page surface)
- a `ThumbnailPanel` and `OutlinePanel` (the sidebar contents for this tab)
- a `SearchService(adapter)` for single-document find
- per-tab search cursor state (`search_hits`, `current_hit_index`)

The `PageView` is the only child of `DocumentView` that displays inside the
tab area. The thumbnail and outline panels are exposed as properties so
`MainWindow` can host them in dock-area `QStackedWidget`s, one per dock,
swapping the visible panel on tab change. This avoids re-parenting on every
tab switch and preserves panel state (selection, expansion, scroll position)
per tab.

`DocumentView` proxies `PageView`'s three signals (`page_changed`,
`zoom_changed`, `view_mode_changed`) outward. `MainWindow` connects to these
proxies on tab change and disconnects on the previous tab, so the status bar
and view-mode menu always reflect the active tab.

**Tab-add ordering trap.** `QTabWidget.addTab` fires `currentChanged`
synchronously when it's the first tab. `_on_tab_changed` runs from that
signal and needs to find the sidebar panels already in their stacks to make
them current. `_add_tab` therefore adds the panels to the sidebar stacks
*before* calling `addTab`. Skipping this order leaves the first tab with
empty thumbnail and outline panels until the user switches tabs and back.

**Programmatic vs user-initiated tab switches.** `_on_tab_changed` closes
the search toolbar by default (so single-document searches don't leak across
tabs). Cross-document navigation calls `setCurrentIndex` to follow F3 across
docs; if that close were unconditional it would also drop the cross-search
result set mid-walk. The guard is "close on tab change only when no
cross-search is in flight" (`not self._cross_search_results`).

**Tab lifecycle.** Open via `File → Open` or `Open Recent`; close via the X
button on each tab, `Ctrl+W`, or `File → Close Tab`. Closing the last tab
returns to the empty-state placeholder. `closeEvent` walks the tab list and
calls `close_document()` on each `DocumentView` before letting Qt shut down.

**Shortcuts** for tab management: `Ctrl+W` closes the active tab,
`Ctrl+PgDown` / `Ctrl+PgUp` cycle through tabs.

## The PageView Widget

`pdfprism.ui.widgets.page_view.PageView` is the central viewing surface for
PDF pages, one per tab. It subclasses `QGraphicsView` and holds:

- The per-tab `PageCache` (passed in by `DocumentView`)
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
view's transform on that single item.

**Continuous mode** lays out every page as its own `QGraphicsPixmapItem`
stacked vertically with a fixed gutter. Per-page rect Y offsets are
precomputed when the layout is built and used by `_on_scroll` to update
`current_page` as the user scrolls past page boundaries (the topmost
visible page wins). Navigation via `go_to_page` scrolls to the
corresponding page rect rather than swapping items. Highlights are drawn
on top of every visible page that has hits, so search overlays span the
document instead of being clipped to a single page; the
`_ensure_hit_visible` helper additionally scrolls the current hit into
the viewport in continuous mode.

A `view_mode_changed(ViewMode)` signal fires whenever the mode actually
changes (no-op `set_view_mode` calls are filtered). MainWindow listens
on this signal to keep the View menu's `QActionGroup` checkmark in sync
even if the mode is set programmatically.

**Known limitation.** Continuous mode renders all pages eagerly when the
mode is entered or the document is bound. Lazy on-scroll rendering, and a
two-up "facing pages" layout, are tracked as PR 5.5 candidates.

## PageCache

`pdfprism.ui.page_cache.PageCache` is a thread-safe LRU cache of rendered
page pixmaps, keyed by `(page_index, zoom)`. One cache per tab, owned by
the `DocumentView`. Both that tab's `PageView` and `ThumbnailPanel` are
constructed against the same cache instance.

**Why this exists.** It centralizes the "render a page" call: only the cache
knows about the adapter, only the cache knows how to convert PNG bytes to
`QPixmap`. Consumers ask for `get_or_render(page_index, zoom)` and don't
care whether the result was rendered or replayed. Cross-consumer reuse
happens only when both consumers ask at the same zoom — in practice
`PageView` uses 2.0 and `ThumbnailPanel` uses 0.25, so the bigger win is
intra-consumer (repeat visits to the same page, scrollback through
thumbnails) rather than cross-consumer sharing.

**Per-tab vs shared cache.** Per-tab is simpler (no composite-key
collisions across documents), memory is naturally bounded per tab, and
closing a tab releases the cache entirely. The cost is no cross-tab
sharing for identical pages — acceptable given a person rarely opens the
same PDF in two tabs at once.

**Rebinding.** `set_adapter(adapter)` clears the cache and binds a new
adapter. `set_adapter(None)` unbinds and clears. Both `PageView` and
`ThumbnailPanel` call this when their own `set_adapter` is invoked.

**Eviction.** Default max 64 entries. LRU by access — both `get()` and
`get_or_render()` promote the entry on hit.

**Concurrency.** A `threading.Lock` guards all reads and writes. Future
async rendering (a PR 3.5 candidate if real-world docs prove laggy) can
submit work from a worker thread without further coordination.

**Placeholder behavior.** If `get_or_render` is called with no adapter
bound, it returns an empty `QPixmap`. Consumers treat that as "show
nothing".

## Thumbnails and Outline Sidebars

The left side of `MainWindow` has two tabified dock widgets (Thumbnails
in front by default). Each dock's content is a `QStackedWidget` that
contains one placeholder widget at index 0 and one panel per open tab
afterwards. On tab change, MainWindow calls `setCurrentIndex` on each
sidebar stack to show the active tab's panel. Closing a tab removes the
corresponding panel from both stacks before the `DocumentView` is
deleted; otherwise the re-parented panels would outlive their tab.

`View → Thumbnails` (F4) and `View → Outline` (F5) toggle each dock via
Qt's built-in `QDockWidget.toggleViewAction()`.

`ThumbnailPanel` (`QListView` + `ThumbnailModel`) shows one small pixmap
per page, rendered through the tab's `PageCache` at zoom 0.25.
`IconMode + Flow.TopToBottom + no-wrap` gives the Acrobat-style vertical
strip; `IconSize` is capped at 160×220.

`OutlinePanel` (`QTreeView` + `OutlineModel`) renders the document's
outline. The adapter returns a flat `list[OutlineItem]` in document order;
the model converts that to a tree via a stack-based pass: for each item,
pop nodes whose level is at or above the item's level until the stack top
is a strict ancestor, then attach. Each `OutlineNode` carries a back-pointer
to its parent so `QAbstractItemModel.parent()` can navigate up, and stores
its target `page_index` so a click can emit `page_selected(int)` without
re-walking the tree.

**Signal wiring inside DocumentView (kept off MainWindow's plate).**

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
single-doc cursor *delegation* but the actual cursor (`search_hits`,
`current_hit_index`) lives on the active `DocumentView`, so each tab's
search state survives tab switches.

`SearchService.find_all(term, *, case_sensitive=False, whole_word=False)`
walks the document via the adapter and returns a flat list of `SearchHit`s
in page order. Two paths:

- **Fast path** (both flags off, default): delegates to
  `DocumentAdapter.search_page`, which uses PyMuPDF's native search with
  `quads=True`.
- **Slow path** (either flag on): iterates `DocumentAdapter.extract_words`
  and filters in Python. Hits cover whole words even when the term is a
  substring. Filtering above the adapter is a service concern -- the
  same Python logic works against any future adapter without per-engine
  reimplementation, which is exactly why `extract_words` is a Protocol
  method rather than a service-internal call to `pymupdf` directly.

Cross-document search (`find_all_across`) accepts the same kwargs and
passes them through to per-doc search, so toggle behavior is identical
in both scopes.

`SearchBar` (`QLineEdit` + `Aa` / `[w]` toggle buttons + scope dropdown
+ Prev/Next buttons + match counter + close button) is a pure UI shell.
It emits `find_requested(str)` on Enter (with whitespace stripped),
`next_requested` and `prev_requested` on its buttons, and `closed` on
the X button or Escape. The toggle state is exposed via the
`case_sensitive` and `whole_word` properties; MainWindow reads them at
find time and passes them through to `SearchService`. `clear()` empties
the input and counter but deliberately leaves the toggles and scope
alone -- they describe how the user wants to search, not what they
searched for last. The widget does not know about documents, services,
or page views.

`PageView` exposes `set_search_hits(list[SearchHit])`, `set_current_hit(
SearchHit | None)`, and `clear_search()`. The hits are stashed in state;
when the view renders any page, it filters hits to that page and draws
each as a translucent `QGraphicsPolygonItem` on the scene at z-value 1
(above the cached pixmap). Yellow for non-current hits, orange for the
one `set_current_hit` points to. Because the highlights are scene
overlays rather than baked into the pixmap, the `PageCache` is never
invalidated by search, and the existing zoom transform scales highlights
along with the page. In continuous mode the same machinery draws
overlays on every visible page that has hits, and `_ensure_hit_visible`
scrolls the current hit into the viewport.

**Signal wiring (MainWindow, single-doc path).**

- `search_bar.find_requested(term) → _on_find`: runs the active tab's
  service, stashes the result on the active tab, points the cursor at hit
  0, calls `page_view.set_current_hit`, updates the counter.
- `search_bar.next_requested / prev_requested → _on_find_next /
  _on_find_prev`: advance the active tab's cursor with Python `%` modulo
  for Acrobat-style wrap, then `_update_current_hit`.
- `search_bar.closed → _on_close_search`: clears active tab's state and
  hides the toolbar.

**Shortcuts** come from `QKeySequence.StandardKey`: `Ctrl+F` (Find),
`F3` (FindNext), `Shift+F3` (FindPrevious) on Windows/Linux.

**Rotation handling.** PyMuPDF returns search rects and word rects in
*unrotated* page coordinates. The rendered pixmap is in *layout*
(rotated) coordinates, so without projection the overlays land where
the text would be if the page weren't rotated. The adapter projects
quads (in `search_page`) and word rects (in `extract_words`) through
`page.rotation_matrix` on rotated pages so overlays track the
displayed glyphs.

Empirical note worth keeping: in PyMuPDF 1.26, it is `rotation_matrix`
that maps unrotated -> layout, despite the docstring wording.
`derotation_matrix` goes the other way. If a future PyMuPDF version
swaps these conventions, the `TestRotationProjection` tests in
`test_pymupdf_adapter.py` will fire and tell us to flip the matrix.

Search hits carry an optional `quad: Quad | None` field. The adapter
populates it only on rotated pages (axis-aligned hits on rotation-0
pages leave it `None` since the bounding rect already describes the
shape). `PageView` builds its `QGraphicsPolygonItem` from `quad` when
present and from the four bbox corners otherwise -- one rendering path,
no special-casing.

**Known limitation.** `extract_words` (used by the slow path for
case-sensitive and whole-word search) projects only the axis-aligned
bounding rect of each word, since `get_text("words")` does not expose
quads. On rotated pages, slow-path hits therefore use rectangular
highlights aligned to the layout axes rather than tight quads around
rotated glyphs. The combination of rotated content + case-sensitive or
whole-word search is rare; the loss is cosmetic, and the fast path on
the same content does get proper quads.

## Cross-document Search

The SearchBar grows a small scope dropdown next to the input
(`SearchScope.CURRENT` / `SearchScope.ALL_OPEN`). When scope is
`ALL_OPEN`, MainWindow dispatches the find through
`SearchService.find_all_across(adapters, term)` (a `@staticmethod`),
which walks every open tab's adapter in tab order and returns a flat
`list[CrossDocHit]`. Each `CrossDocHit` carries the originating
`doc_index` and the underlying `SearchHit`, so results can be tagged back
to their tab without holding adapter references.

A `SearchResultsPanel` widget (right-side dock) renders the results as a
two-level `QTreeWidget`: top-level items are documents (`<filename> (N
hits)`); children are hits (`Page M`, 1-based). Hits store their
flat-list index in `UserRole` so a click emits `result_selected(int)`,
which MainWindow turns into a `_jump_to_cross_hit` call.

**The cross-search cursor.** MainWindow keeps
`_cross_search_results: list[CrossDocHit]` and `_cross_search_index: int`.
`_jump_to_cross_hit(index)` switches to the result's tab, clears stale
highlights on every other tab, draws a single-hit highlight on the target
tab via the same `PageView.set_search_hits` / `set_current_hit` machinery
single-doc search uses, updates the counter (`set_aggregate_count` with
the current cursor position), and selects the corresponding row in the
results panel. F3 and Shift+F3 in `ALL_OPEN` scope advance / decrement
the cursor with wrap, so navigation walks the whole flat list across
documents.

**Why a guard around `_on_tab_changed`.** Switching tabs normally closes
the search toolbar (which also calls `_reset_search_state` for the active
tab plus `_clear_cross_search`). `_jump_to_cross_hit` switches tabs
internally; if the close ran during that programmatic switch, the
cross-search result set would be dropped mid-walk, and the next F3 would
find an empty cursor and become a no-op. The guard
(`not self._cross_search_results`) skips the close while cross-search is
in flight; the toolbar stays visible and the cursor stays valid.

**Lifecycle.** The results dock is hidden initially and toggled on by
`_on_find_all_open` whenever cross-search runs (even with zero hits, so
the user sees "No matches" instead of staring at a populated results
panel from a previous search). It hides again when:

- the user closes the search toolbar (`_on_close_search`)
- a single-doc search runs (the first thing `_on_find` does on the
  CURRENT branch is call `_clear_cross_search`)
- a tab is closed (cross-search indices reference tabs by position, so
  removing a tab invalidates them and we drop the result set rather than
  try to remap)
- the last tab closes (empty state)

**Counter format.** `SearchBar.set_aggregate_count(total, docs, current=0)`
produces `"No matches"` when total is 0, `"N matches"` or `"N in M docs"`
when current is 0 (just after a search with no cursor displayed), and
`"X of N"` or `"X of N in M docs"` when current is set.

**What's not done yet.** Per-hit snippets in the results panel need text
extraction above the adapter; deferred to PR 7 (text extraction) so this
PR doesn't grow the adapter contract. Persisting open tabs across sessions
is a PR 6.5 candidate.

## Extraction

Text and image extraction live in `services/extract.py` behind a single
`ExtractService` class bound to one adapter, mirroring `SearchService`.
The adapter contract grew two methods -- `extract_text(index) -> str`
and `extract_images(index) -> list[ExtractedImage]` -- and the service
composes higher-level operations on top of those plus `extract_words`
(originally added in PR 4.5 for the search slow path).

Operations the service exposes:

- `text_for_page(i)` -- single-page text, thin wrapper.
- `text_full_document(page_range=None)` -- concatenates pages with
  form-feed (`\f`) separators, the conventional plain-text separator
  for paged dumps.
- `text_in_rect(i, rect)` -- words on page `i` overlapping the given
  rect, joined in reading order. Used by the right-click "Extract
  Selection to File" path. Intersection is "any overlap," matching
  how viewer selections work elsewhere.
- `snippet_around(i, rect, max_chars=80)` -- the line of text
  containing the hit, trimmed with ellipses around the hit's horizontal
  midpoint. Used to label cross-search results: `Page N: ...context...`.
- `images_full_document(out_dir, page_range=None)` -- writes one file
  per image, named `page<N>_img<M>.<ext>` with 1-based N and M.

The shared helper `_join_words_as_lines` reconstructs line breaks from
y-coordinate jumps using each word's own height as the threshold. It is
also imported by `PageView` for `selected_text`, so word-rect output and
selection text use one reading-order algorithm.

**Selection mechanic.** `PageView` grew a `ToolMode` enum (`HAND` /
`SELECT`) parallel to the existing `ViewMode`. HAND keeps the PR 2
behavior: scroll-hand drag pans. SELECT switches `setDragMode` to
`NoDrag` so `PageView` handles drag itself in `mousePressEvent` /
`mouseMoveEvent` / `mouseReleaseEvent`. On drag, the rect is mapped
from scene coordinates to PDF page coordinates (divide by
`_RENDER_SCALE`), `extract_words` is fetched for the current page,
and overlapping words are stored in `_selected_words`. The overlay is
rendered as translucent blue `QGraphicsPolygonItem`s -- the same scene-
overlay pattern the search highlights use, just a different color and
list. `selected_text` joins the words via `_join_words_as_lines` for
consistent line-break reconstruction.

Selection is intentionally single-page only in this PR. Continuous-mode
selection across page boundaries needs page-relative coordinate mapping
that the current scene layout doesn't expose cleanly; deferring rather
than half-implementing keeps the contract clear.

**Tool-mode persistence.** MainWindow owns the canonical `_tool_mode`,
loaded from QSettings under `tool/mode` in `__init__` (default HAND),
saved on every `_on_set_tool_mode` call. Same pattern as `view/dark_mode`
from PR 5. UI sync (`_sync_tool_mode_ui`) updates two things: the
exclusive `QActionGroup` for Hand Tool / Select Text in the View menu,
and the `_tool_indicator` `QLabel` in the status bar. On open of a new
tab, `_apply_tool_mode_to_all_tabs` (or the open-flow inline call) pushes
the current mode into the new `DocumentView`'s `PageView` so freshly
opened tabs match the user's chosen mode.

**Clipboard and context menu.** Ctrl+C is wired to a `MainWindow._on_copy`
slot that reads `selected_text` from the active tab's PageView and pushes
it to `QApplication.clipboard()`. Right-click on `PageView` opens a
context menu via `contextMenuEvent` with Copy + Extract Selection to
File. The two menu items emit `copy_requested` / `extract_selection_
requested` signals; MainWindow connects them at tab-open time, then the
save-as path lives in `_on_extract_selection` with a `QFileDialog`
anchored on `extract/last_dir` from QSettings.

**Extract menus.** `File -> Extract -> Text...` and `File -> Extract ->
Images...` open an `ExtractDialog` (page-count + kind) for picking all
pages vs a range. The dialog returns a 0-based half-open `range` so the
service can use it directly. After accept, MainWindow drives a file or
directory picker (also remembering `extract/last_dir`), then calls
`ExtractService.text_full_document` or `images_full_document`. The image
path posts a final "Wrote N image(s)" info dialog because writing to
a directory has no implicit "opened thing" the user can see.

**Cross-search snippets.** When the search bar runs in `ALL_OPEN` scope,
MainWindow now builds a parallel `snippets` list by calling
`ExtractService.snippet_around` per hit (one service per doc cached in
a local dict to avoid re-wrapping the adapter). `SearchResultsPanel.
set_results` got an optional third `snippets` argument; when present,
each row reads `Page N: snippet`. Empty snippet strings fall back to
plain `Page N` so any extraction failure stays cosmetic.

**Known limitations.** No formatted-text copy (HTML/RTF); plain text
only. No glyph-level selection; word granularity covers the 90% case
and glyph-level is a candidate for a later PR. No selection in
continuous mode. No click-an-image-to-save; whole-document extract via
the menu covers the bulk case.

## Page Operations

PR 8 introduces single-document page mutations (rotate, delete, insert,
duplicate, move/reorder, crop) plus Save / Save As, threaded through
three layers in a way that mirrors the rest of the architecture: the
engine work lives on the adapter, semantic naming lives in the service,
and modified-state tracking + UI plumbing live on `DocumentView`.

**Save model.** Mutations are staged in memory; nothing hits disk until
the user invokes Save (Ctrl+S) or Save As (Ctrl+Shift+S). This is the
Acrobat-style staging model: the active tab carries a dirty flag, the
tab title shows ` *` when modified, and closing a modified tab (or the
whole app) prompts Save / Discard / Cancel. No undo command stack in
v1; close-without-save is the coarse-grained undo, which is enough for
Milestone 3 and aligns with PR 11's needs (redaction is irreversible
once applied, so staging matters more than per-operation undo).

**Adapter contract.** The `DocumentAdapter` Protocol grew seven
mutation methods plus an `is_dirty` property and a `save` method:

- `rotate_page(index, degrees)` -- 90, 180, or 270 only (additive to
  the page's existing rotation).
- `delete_pages(indices)` -- deduplicated and applied in reverse order
  so earlier indices remain valid; raises if every page would be
  deleted.
- `insert_blank_page(index, width, height)` -- inserts before `index`;
  use `index = page_count` to append.
- `duplicate_page(index)` -- inserts the copy right after the source.
- `move_page(from_index, to_index)` -- `to_index` is the desired
  **post-removal** index. The PyMuPDF implementation translates this
  to the engine's "insert before original-coords index" semantics,
  using the `-1` sentinel for move-to-end. (This was verified
  empirically against PyMuPDF 1.27.)
- `crop_page(index, margins)` -- margins are
  `(top, right, bottom, left)` in PDF points; `(0, 0, 0, 0)` clears
  any existing crop.
- `save(path=None)` -- writes the document to disk. Default uses the
  path the document was opened from (in-place save via a temp file
  + atomic rename to dodge Windows file-lock issues; close + reopen
  to keep the adapter usable afterward). A non-`None` path performs
  Save As and updates the tracked path so subsequent saves stay
  in-place.

Two new exception types -- `PageOperationError` for invalid mutations
(bad rotation angle, empty document after delete, negative crop
margins) and `DocumentSaveError` for I/O failures -- join the existing
hierarchy under `PdfPrismError`.

**Service layer.** `services/pages.py` is the smallest service in the
codebase: each operation is a one-liner that delegates to the adapter.
The layer exists for symmetry with `SearchService` and `ExtractService`,
to give the operations user-intent names (`rotate_right`, `rotate_left`,
`append_blank_page`, `insert_blank_page_after`/`_before`), and so future
composite operations (PR 11 redaction will compose with crop; PR 8.5
cross-doc page insertion will create temp adapters here) have somewhere
to live without growing the adapter contract.

**Modified-state tracking on DocumentView.** The adapter holds the
truth (`is_dirty`), DocumentView caches the last-known value and
emits `modified_changed(bool)` only when the value flips. Every
page-op DocumentView exposes (`rotate_page`, `delete_pages`, etc.)
does the same dance:

1. Mutate the adapter.
2. Clear `_page_cache` (pixmaps now refer to stale page indices).
3. Re-bind the **thumbnail panel** to the adapter -- before the page
   view -- so its model knows the new page count before
   `PageView.set_adapter` emits `page_changed(0)` which routes
   through to `ThumbnailPanel.set_current_page` -> `scrollTo` ->
   `rowCount`/`data`. Getting this order wrong is the kind of bug
   that only surfaces on delete-last-page (the smoke caught it).
4. Re-bind the page view (which triggers re-render).
5. Call `_refresh_modified()` to fire the signal if the dirty state
   flipped.

All UI code -- MainWindow slots, future Organize panel -- routes
mutations through DocumentView's methods, never the adapter directly.
That's the single insertion point an undo command stack would hook
into in a future PR.

**MainWindow surface.** New actions:

- File menu: Save (Ctrl+S), Save As... (Ctrl+Shift+S). Both are
  disabled when no tab is open; Save is also disabled when the active
  tab is clean. `_refresh_save_actions` runs on tab open, tab change,
  modified-state flip, and empty-state transitions.
- Edit → Page submenu: Rotate Right (Ctrl+R), Rotate Left
  (Ctrl+Shift+R), Rotate 180°, Insert Blank Page After, Duplicate
  Current Page, Move Page... (Ctrl+Shift+M), Crop Page..., Delete
  Current Page (with confirmation, blocked when only one page
  remains).

Slots route through `_current_page_index` (returns the active tab's
current page or `None` for the empty state) and `_run_page_op` (wraps
the call in a try/except that surfaces engine errors as a critical
QMessageBox). Insert-blank defaults the new page's dimensions to the
current page's so the document stays visually consistent. Move uses
`QInputDialog.getInt` with 1-based UI numbering to match the
page-navigator convention.

**Crop dialog.** `ui/dialogs/crop.py` `CropDialog` is a modal with
four `QDoubleSpinBox`es (top/right/bottom/left in PDF points) plus a
Reset button that zeros all four (used to clear an existing crop).
Spinbox upper bounds are `dim - 1` so the crop can't collapse the
page to zero area; the adapter has its own "resulting area must be
positive" check as a backstop. Unit conversion to inches/mm and a
live preview are deferred to PR 9, where the Organize panel will
host a richer crop UI.

**Test fixtures.** Mutation tests need a writable copy of
`sample.pdf`. `tests/conftest.py` exposes a `mutable_pdf_path`
fixture that copies the committed sample into the per-test
`tmp_path`. Adapter tests use a `mutable_adapter` fixture that opens
the copy; DocumentView tests use `mutable_view`. The committed
sample is still treated as effectively read-only.

**Deferred to PR 8.5/9.** Cross-document operations (split, merge,
insert pages from another PDF, extract-to-new-file) live in PR 8.5
to keep PR 8 reviewable. Rich Organize panel UI (drag-reorder,
multi-select, live crop preview) is PR 9. Undo command stack is
deferred -- close-without-save is the v1 undo story.

## Cross-Document Page Operations

PR 8.5 adds the four operations that span multiple documents:
extract pages to a new file, insert pages from another file, split
one document into many, and merge many documents into one. Together
they finish Milestone 3's page-operation surface; PR 9 then lifts
these into the rich Organize Pages panel.

**Adapter additions.** Two new methods on ``DocumentAdapter``:

- ``new_document()`` -- close any open doc and replace with an
  empty in-memory PDF (``_path = None``). The empty doc has
  ``is_dirty == False``; ``save()`` without an explicit path raises
  because there is no source path to default to. Always followed by
  ``insert_pdf`` in practice -- PyMuPDF refuses to save a zero-page
  document.
- ``insert_pdf(source, from_index, to_index, at_index)`` -- copy a
  page range from another adapter into self. ``to_index`` is
  **inclusive** (matches PyMuPDF native semantics and reads more
  naturally for users -- "insert pages 3 through 7"). ``at_index``
  is 0-based; ``page_count`` means append. Self becomes dirty;
  source is unchanged.

``insert_pdf`` is the only place the adapter reaches across
instances. The implementation reads the source's private ``_doc``
attribute because PyMuPDF's ``Document.insert_pdf`` wants a
``pymupdf.Document``, not a Protocol. This same-engine assumption
is documented in code; if we ever swap engines, we swap all of
them at once.

**Service layer.** ``services/pages.py`` gains three methods on
``PageService`` and one free function:

- ``extract_to_file(from_index, to_index, output_path)`` -- create
  a fresh adapter, ``new_document`` it, ``insert_pdf`` the range,
  ``save(output_path)``, close. Source untouched.
- ``insert_from(source_path, from_index, to_index, at_index)`` --
  open source headlessly, ``insert_pdf`` into self, close. Self
  becomes dirty.
- ``split(breakpoints, output_dir, stem)`` -- breakpoints are
  0-based slice-start indices (the first slice always starts at
  0). Files are named ``f"{stem}-{N:0Wd}.pdf"`` with N 1-based
  and W matching the digit count of the largest output. Returns
  the written paths in slice order.
- ``merge(sources, output_path)`` -- free function, not a
  ``PageService`` method, because it fundamentally takes a list of
  adapters rather than binding to one. Each source's **in-memory**
  state is merged (including any unsaved mutations). Sources are
  not modified. Raises ``PageOperationError`` if given fewer than
  two sources.

**Dialogs.** Four new modals in ``ui/dialogs/`` mirror the four
operations. Each dialog is dumb -- it gathers user input and
exposes computed values via properties, with no knowledge of
adapters or services. The split dialog runs its own input
validation (out-of-range page numbers, non-integer text) on OK and
stays open with a warning if the input is invalid; the calling
slot only sees a valid breakpoints list when ``Accepted``. The
merge dialog uses a ``QListWidget`` with item check states for
selection, plus Up/Down buttons for ordering -- richer drag-reorder
is deferred to the PR 9 Organize panel where drag is the main
interaction. All four dialogs disable OK until the required output
path (or directory) is set, so the user can't accidentally start
the operation without a destination.

**MainWindow surface.** A new File → Pages submenu groups all
four operations: Extract Pages to File..., Insert Pages from
File..., Split Document..., Merge Documents... The first three
enable with any open tab; Merge requires at least two. Each slot
follows the same shape: build dialog, exec, route through
service/adapter, surface errors via QMessageBox. Insert is the
only one that mutates the bound document; it goes through a new
``DocumentView.insert_from`` proxy that re-binds the thumbnail
panel and page view exactly like PR 8's single-doc proxies
(thumbnail before page view -- see Page Operations for the
rationale). Merge opens the result as a new tab so the user can
verify what they just produced; Extract and Split leave the user
on the source document because the outputs are conceptually side
files.

**Source-file handling for Insert.** The source PDF is opened
headlessly twice: once briefly inside the slot to read its page
count (so the dialog can bound its spinboxes), then again inside
``PageService.insert_from`` to actually do the insert. Two opens
are cheap and keep the dialog stateless; the alternative would be
for the dialog to hold an adapter through its lifetime, which
muddies the lifecycle.

**No tab for source documents.** Insert opens its source
headlessly and closes it after the insert; it does not stay
around as a tab. The source is a one-shot resource for the
operation. If the user wants to view it, they open it separately.

**Deferred to PR 9.** Drag-to-reorder for merge, multi-select
page operations, live crop preview, and the Organize Pages panel
that surfaces the cross-doc operations as toolbar buttons
alongside the single-doc ones. Inches/mm unit conversion for crop
is also a PR 9 candidate. Customizable filename patterns for
split outputs are deferred indefinitely.

## Organize Pages Panel

PR 9 adds the rich page-editing surface that PR 8 (single-doc
operations via menu) and PR 8.5 (cross-doc operations via menu)
set up. The panel is a dockable widget on the right of the main
window, hidden by default, toggled with F6.

**Composition.** Two classes in ``ui/widgets/organize_panel.py``:

- ``OrganizePanel`` (``QListView``) is the bare grid -- ``IconMode``
  + ``LeftToRight`` flow + ``Wrapping`` for the grid layout,
  ``ExtendedSelection`` for Ctrl/Shift multi-select. Custom
  ``OrganizeModel`` (``QAbstractListModel``) feeds pixmaps from the
  shared ``PageCache``; near-identical to ``ThumbnailModel`` but
  not shared because the selection and drag semantics diverge.
- ``OrganizePagesPanel`` (``QWidget``) is the composite that
  MainWindow docks: a ``QToolBar`` of selection-aware actions, the
  ``OrganizePanel`` grid, and a status ``QLabel`` showing the
  selection count. It re-emits the grid's operation signals so
  consumers don't reach into ``._grid``.

**Signal-based operation contract.** The panel never touches the
adapter directly. It emits intent signals -- ``rotate_requested
(indices, degrees)``, ``delete_requested(indices)``,
``duplicate_requested(indices)``, ``move_requested(from, to)`` --
and ``DocumentView`` owns the mutation. This keeps the panel
ignorant of adapters and consistent with PR 8/8.5's discipline:
every page mutation goes through ``DocumentView`` so the cache
clears, every panel re-binds, and the dirty flag refreshes in one
place.

**Drag-to-reorder.** PR 9 ships single-page drag only. We deliberately
use ``DragDropMode.DragDrop`` (not ``InternalMove``) and override
``dropEvent`` to capture the drop position, emit ``move_requested``,
and call ``event.ignore()`` so Qt never moves a row in its own
model. The host owns the mutation through the adapter; the panel
is re-bound afterwards. Single source of truth.

Translating Qt's drop indicator semantics to PR 8's
``DocumentView.move_page(from, to)`` contract needs care because
Qt's ``dest_row`` uses insertion-position semantics while
``move_page``'s ``to_index`` is the post-removal target:

- Forward move (``from < dest``): ``to = dest - 1``
- Backward move (``from > dest``): ``to = dest``
- ``from == dest``: no-op

The translation is captured in ``OrganizePanel._qt_drop_to_move_page``
and verified by ``TestDropTranslation``; the actual semantics were
found empirically against Qt 6.11.

**Multi-select operations.** ``DocumentView`` exposes three new
slots wired to the panel's request signals:

- ``_on_organize_rotate(indices, degrees)`` -- loop ``rotate_page``,
  rebind once at end. Order doesn't matter for rotation.
- ``_on_organize_delete(indices)`` -- delegates to ``delete_pages``
  which already takes a list (PR 8 primitive).
- ``_on_organize_duplicate(indices)`` -- loop ``duplicate_page``
  in **reverse** index order so earlier indices stay valid as we
  insert copies.

Each slot ends with the standard cache-clear + thumbnail-rebind +
organize-rebind + page-view-rebind + ``_refresh_modified`` dance,
matching PR 8's seven page-op proxies (which were also extended to
re-bind the organize panel).

**Widget-scoped keyboard shortcuts.** The panel's toolbar actions
carry shortcuts with ``Qt.ShortcutContext.WidgetWithChildrenShortcut``:
Ctrl+R rotates the selection right, Ctrl+Shift+R rotates left,
Delete deletes, Ctrl+D duplicates, Ctrl+A selects all. Crucially,
Ctrl+R also exists at the MainWindow scope (PR 8: rotate the
**current** page). When the panel has focus, Qt's shortcut
disambiguation routes Ctrl+R to the widget-scope action (rotate
**selection**); when the page view is focused, the MainWindow
action fires. Same keystroke, contextually scoped behaviour --
"rotate whatever you're looking at".

**Per-tab ownership.** Following the established pattern from
``ThumbnailPanel`` and ``OutlinePanel``, each ``DocumentView``
owns its own ``OrganizePagesPanel`` instance. MainWindow holds a
``QStackedWidget`` (``_organize_stack``) inside the dock; on tab
switch we ``setCurrentWidget`` to the active tab's panel. On open,
we ``addWidget``; on close, ``removeWidget``. When no tabs are
open, the stack shows a placeholder ``QWidget`` (index 0).

**Session persistence.** Visibility of the organize dock is saved
in the per-tab session state alongside the thumbnail and outline
dock visibilities. On session restore we read with
``state.get("organize_dock", False)`` so older session files
without the key default to hidden (the new feature's default).

**Deferred to PR 9.5.** Multi-page drag, crop on selection (the
headline of PR 9.5 is the live crop preview), extract selection to
file (needs non-contiguous design decision), external file drag
(drop a PDF from Explorer to insert pages). The PR 9 design
anticipates these extensions: the toolbar add pattern is uniform,
``selected_indices`` is the universal selection getter, and the
request-signal contract scales without changes.

### PR 9.5 additions

PR 9.5 extends PR 9 without changing the panel-composition or
signal-routing story. Three additions land as pure extensions.

**Live crop preview in ``CropDialog``.** A new ``CropPreview``
sub-widget renders the target page at zoom 0.25 via the shared
``PageCache`` (no extra rasterisation cost) and overlays the crop
rectangle: cropped-away regions are dimmed with a semi-transparent
black band around the retained interior, the interior itself is
outlined in a calm blue. Spinbox ``valueChanged`` signals push the
new margins into the preview via ``set_margins``, which triggers a
repaint but not a re-render. The pixmap is scaled down only when
it exceeds the preview budget (280 x 360 pixels) -- small thumbnails
stay pixel-perfect. Over-crop cases (margins that would collapse
the interior) clamp width/height to non-negative rather than
raising in the preview; the adapter's ``crop_page`` is the source
of truth on validity.

``CropDialog``'s constructor gains an optional ``page_cache``
argument. When absent, the dialog degrades to the PR 8 form-only
layout -- keeping every existing caller working -- and when
present, the preview is inserted between the info label and the
margin form. Both the panel's Crop Selection action and
MainWindow's ``Edit -> Page -> Crop Page...`` action now pass the
active tab's ``organize_panel.cache`` so the preview is available
in every entry point that reaches ``CropDialog``.

**Crop-on-selection.** The panel gains a
``crop_requested = Signal(list, tuple)`` alongside the PR 9
operation signals. The composite's ``_on_crop_requested`` slot
opens ``CropDialog`` sized against the *smallest* selected page so
the entered margins are safe for every page in the selection (an
uniform-margins design decision that matches Acrobat's multi-page
crop). Absolute-points semantics from PR 8 are preserved rather
than converted to percentages: a percent-of-page mode would be its
own polish item. ``DocumentView._on_organize_crop`` iterates the
selection forward (order-independent for crop) and calls
``adapter.crop_page(idx, margins)`` for each; the standard PR 9
rebind dance (cache clear, thumbnail rebind, organize rebind, page
view rebind, refresh_modified) follows. Failure semantics are
fail-fast: if an adapter call raises mid-loop, earlier iterations'
state remains applied. This matches PR 9's rotate/delete/duplicate
behaviour and is pinned by an explicit test so a later refactor to
atomic rollback would be a conscious change.

**Extract-selection-to-file.** A new
``PageService.extract_pages_to_file(indices, output_path)`` handles
the non-contiguous case that PR 8.5's contiguous ``extract_to_file``
can't. The implementation is a fresh output adapter plus a loop of
single-page ``insert_pdf`` calls, one per index, appending at
``out.page_count`` each time. Input order is preserved (not
sorted), duplicate indices produce duplicate output pages
(multiplicity kept), and an empty ``indices`` list raises
``PageOperationError`` rather than saving a zero-page PDF (PyMuPDF
refuses that anyway; raising early surfaces caller bugs). The
panel's ``_on_extract_requested`` slot opens ``QFileDialog.getSaveFileName``
with a suggested name computed by ``_suggest_extract_filename``:
contiguous selections get ``<stem>_pages_<from>-<to>.pdf`` (1-based
for human-friendliness), non-contiguous selections get
``<stem>_pages_selection.pdf``. ``DocumentView._on_organize_extract``
is read-only against the source document -- no cache clear, no
panel rebind, no dirty flag change -- symmetric with PR 8.5's
``extract_to_file``.

**MainWindow integration.** Two menu entries surface the panel-scope
actions at the MainWindow level: ``Edit -> Page -> Crop Selection...``
next to the existing ``Crop Page...``, and
``File -> Pages -> Extract Selection...`` next to the existing
``Extract Pages to File...``. Both slots delegate to the active
tab's ``organize_panel._on_crop_requested`` / ``_on_extract_requested``
rather than duplicating dialog logic -- MainWindow's role here is
discoverability, not implementation. Enable/disable is gated on
``(tab open) AND (organize panel selection non-empty)``, tracked
via a subscription to ``organize_panel.selection_changed`` set up
in ``_on_current_tab_changed`` (with the symmetric disconnect on
tab-out). Menu-scope shortcuts are intentionally omitted; the
panel's own ``Ctrl+E`` for extract with ``WidgetWithChildrenShortcut``
context stays authoritative.

## Theme

`pdfprism.ui.theme.DARK_QSS` is a Qt Style Sheet (QSS) string applied
app-wide when dark mode is enabled. It covers `QMainWindow`, `QMenuBar`,
`QMenu`, `QToolBar`, `QToolButton`, `QStatusBar`, `QDockWidget`,
`QListView`, `QTreeView`, `QLineEdit`, `QPushButton`, `QScrollBar`, and
`QTabBar`. Backgrounds are `#2b2b2b` / `#353535` / `#1e1e1e`, foreground
is `#e0e0e0`, accent is `#0078d4`.

`View → Dark Mode` is a checkable `QAction` whose state is persisted
under the QSettings key `view/dark_mode` and restored at startup. Toggling
it calls `QApplication.setStyleSheet(DARK_QSS)` to apply, or `""` to
revert to the platform default. The PDF page itself is rendered by
PyMuPDF and is unaffected — only the chrome around it switches.

Light mode is the platform default style; there is intentionally no
custom light stylesheet.

## Full Screen

`View → Full Screen` (F11) is a checkable `QAction` that toggles a
distraction-free presentation: menubar, both toolbars, status bar, both
sidebar docks, the search results dock, and the tab bar all hide; the
window goes `showFullScreen`. Previous visibility of each chrome element
is snapped into `_fullscreen_state` and restored on toggle-off (F11
again, or `Esc` via `keyPressEvent`).

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
opening from history goes through the same code as a fresh open (which
means it opens in a new tab). A `Clear Recent` action at the bottom of
the submenu wipes the list. Entries whose underlying file no longer
exists are filtered out at render time but kept in storage.

`File → Open...` remembers the last successfully chosen directory via
QSettings key `recent/last_dir` and seeds the file dialog with it on
the next invocation.

**`_on_open` vs `_open_path`.** The dialog flow (`_on_open`) is separated
from the work flow (`_open_path`) so the recent-files menu can invoke
the latter directly. `_open_path` canonicalizes the path with
`Path.resolve(strict=False)` (catching `OSError` and falling back to the
original) so two different spellings of the same file collapse to one
recent-files entry.

**Failed-open recovery.** If `_open_path` catches `PdfPrismError`, it
calls `doc_view.deleteLater()` on the half-constructed `DocumentView` so
no orphaned tab is created, then shows the error dialog. No `MainWindow`
state is touched.

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
  and a four-entry outline. Tests assert exact values.
- **Adapter contract tests.** `tests/core/test_pymupdf_adapter.py` covers
  Protocol conformance, every method, and edge cases.
- **Service tests** (`tests/services/`) drive the service against real
  adapters on the test fixture. `SearchService.find_all_across` is
  exercised against two adapters on the same fixture, verifying
  doc-order, page-order, the `CrossDocHit` shape, and the empty-input
  cases.
- **UI widget tests** (`tests/ui/`) use `pytest-qt`'s `qtbot` fixture:
  instantiate the widget, drive its public API, assert state and emitted
  signals. `DocumentView`, `SearchResultsPanel`, and the existing per-tab
  widgets each have their own test file.
- **MainWindow tests** (`tests/ui/test_main_window.py`) drive the
  top-level integration: empty state, open / close / switch tabs,
  sidebar binding, cross-search dispatch, F3 traversal across docs.
  Modal `QMessageBox.critical` is monkeypatched out to keep failure-path
  tests headless, and a per-test `_isolate_qsettings` fixture redirects
  `QSettings` to `tmp_path` so tests do not pollute the real
  recent-files / dark-mode state.
- **Dock visibility asserts.** Use `QDockWidget.isHidden()`, not
  `isVisible()`. `isVisible()` is False until the toplevel window is
  shown, which we never do in tests. `isHidden()` reflects the explicit
  hide/show flag the code actually sets.
- **Autouse `qapp`.** `tests/ui/conftest.py` declares an autouse fixture
  that pulls in pytest-qt's `qapp`.

## Roadmap

Fifteen PRs across five milestones. Each PR is a self-contained branch that
merges via PR review and CI on green.

### Milestone 1 — Reader Core

- **PR 1: Foundation.** Scaffold, license, CI, branch protection (via
  pre-commit hook), `DocumentAdapter` Protocol, `PyMuPDFAdapter`, minimal Qt
  window.
- **PR 2: Navigation and zoom.** `PageView` widget, page navigation, four
  zoom modes, View / Go menus, toolbar, status bar, full keyboard shortcut
  surface.
- **PR 3: Thumbnails and outline sidebars.** Shared `PageCache`,
  `ThumbnailPanel`, `OutlinePanel`. Two tabified `QDockWidget`s on the left.
- **PR 4: In-document text search.** `SearchHit` type, `search_page` on the
  Protocol, `SearchService`. `SearchBar` with Ctrl+F / F3 / Shift+F3.
  `PageView` translucent overlay highlights.
- **PR 4.5: Search hardening.** Case-sensitive and whole-word toggles
  in `SearchBar` (`Aa` / `[w]` buttons), flowing through to a new
  service slow path that filters via `DocumentAdapter.extract_words`.
  Adapter `search_page` now uses `quads=True` and projects results
  through `page.rotation_matrix` so highlights track text on rotated
  pages. `SearchHit` gains an optional `quad` field; `PageView` switches
  to `QGraphicsPolygonItem` so quad-shaped overlays render correctly
  with no special-casing. New `Word` type on `core/types.py` and a new
  `extract_words` method on the Protocol -- a primitive PR 7 will
  reuse.
- **PR 5: View modes, full-screen, dark mode, recent files.** `ViewMode`
  enum and continuous-scroll layout in `PageView`; F11 full-screen with
  state save/restore; manual dark mode via `ui/theme.py` (`DARK_QSS`),
  persisted under QSettings; `File → Open Recent` and last-directory
  memory; `_on_open` / `_open_path` factoring plus `_reset_to_empty_state`
  for clean failed-open recovery.
- **PR 6: Multi-document tabs and cross-PDF search.** New `DocumentView`
  widget owning per-tab adapter, cache, page view, sidebars, and search
  service. `MainWindow` central is now a `QStackedWidget`
  (placeholder + `QTabWidget`); sidebars are `QStackedWidget`s of
  per-tab panels swapped on tab change. New `CrossDocHit` type and
  `SearchService.find_all_across` static method. `SearchBar` scope
  dropdown (`CURRENT` / `ALL_OPEN`); new `SearchResultsPanel` shown in
  a right-side dock when scope is `ALL_OPEN`. F3 / Shift+F3 walk the
  flat cross-search cursor, auto-switching tabs on doc boundaries;
  clicking a result jumps to that tab. New tab-switching shortcuts
  `Ctrl+PgUp` / `Ctrl+PgDown`; `Ctrl+W` now closes the active tab.

### Milestone 2 — Extraction

- **PR 7: Text selection, copy, extract to disk.** New `ExtractedImage`
  type; adapter `extract_text` + `extract_images`; new `services/extract.py`
  with text-in-rect, snippet-around-rect, full-doc text, full-doc image
  extraction. `PageView` `ToolMode` enum (HAND/SELECT), drag-rect word
  selection with blue translucent overlay, `selected_text` property,
  `selection_changed` / `copy_requested` / `extract_selection_requested`
  signals. MainWindow Hand Tool / Select Text actions persisted via
  QSettings, status-bar tool indicator, Ctrl+C clipboard, right-click
  context menu, `File -> Extract -> Text/Images...` menus with a shared
  `ExtractDialog` page-range picker. Cross-search `SearchResultsPanel`
  rows now show `Page N: snippet` when running with `ALL_OPEN` scope.

### Milestone 3 — Page Operations

- **PR 8: single-doc page operations.** Adapter mutation contract
  (`rotate_page`, `delete_pages`, `insert_blank_page`, `duplicate_page`,
  `move_page`, `crop_page`, `save`) plus `is_dirty` and `save_as`-style
  path tracking. New `services/pages.py` `PageService` thin-wraps each
  operation with user-intent naming. `DocumentView` gains `is_modified`,
  `modified_changed` signal, and proxy methods that route every mutation
  so the model and UI stay in sync. MainWindow Save (Ctrl+S) / Save As
  (Ctrl+Shift+S), tab title shows ` *` when modified, close-tab and
  app-quit prompts (Save / Discard / Cancel) for unsaved changes. Edit
  → Page submenu: Rotate Right (Ctrl+R), Rotate Left (Ctrl+Shift+R),
  Rotate 180°, Insert Blank Page After, Duplicate, Move Page...
  (Ctrl+Shift+M), Crop Page... (new `CropDialog`), Delete Current Page
  (with confirmation).
- **PR 8.5: cross-document page operations.** Adapter additions
  ``new_document`` (open empty in-memory PDF) and ``insert_pdf``
  (copy a page range from another adapter). ``PageService`` gains
  ``extract_to_file``, ``insert_from``, and ``split``; a free
  ``merge`` function combines multiple adapters into one file.
  Four new dialogs (``ExtractPagesDialog``, ``InsertPagesDialog``,
  ``SplitDialog``, ``MergeDialog``) and a File → Pages submenu
  surface them.
- **PR 9: Organize Pages UI.** New ``OrganizePagesPanel`` dock
  (right side, F6 toggle, hidden by default) with grid view,
  multi-select, drag-to-reorder, and selection-aware operations
  (rotate / delete / duplicate). Per-tab ownership pattern
  matching ``ThumbnailPanel`` and ``OutlinePanel``. Crop preview
  and multi-select crop/extract deferred to PR 9.5.

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
- **Annotations** (highlights, sticky notes, drawings, stamps).
- **Form creation and form-field editing.**
- **Digital signatures.**
- **PDF/A conversion.**
- **Office docs in "Combine"** (`.docx`, `.xlsx`, `.pptx`).
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
- **Cross-document search.** A search across every currently open tab,
  rendered in the right-side results dock. Distinct from single-document
  search, which highlights matches inline on one tab's `PageView`.
- **DocumentView.** The per-tab container widget owning a document's
  adapter, page cache, page view, sidebars, and search service.
- **PDF/A.** Archival PDF format. Out of scope for v1.
- **PDFium.** Google's PDF rendering engine, used by Chrome and available
  via the `pypdfium2` Python binding. The most likely replacement for
  PyMuPDF if licensing intent ever shifts.
- **Protocol** (Python). PEP 544 structural subtyping. Used here as the
  interface for `DocumentAdapter`.
- **QSS.** Qt Style Sheet — Qt's CSS-like styling syntax. Used by the
  dark-mode theme.
- **Quad.** A general quadrilateral in PDF coordinates. PyMuPDF returns
  `Quad`s (rather than axis-aligned `Rect`s) when text is rotated.
- **Redaction.** Removing sensitive content from a PDF such that it cannot
  be recovered.
- **TOC.** Table of Contents. Synonym for "outline" in PDF terminology.
- **XFA.** Legacy Adobe XML Forms Architecture. Deferred indefinitely.

## Suggested Reading Order

If you are new to the codebase, read in this order:

1. `pyproject.toml` — what we depend on and how the project is built.
2. `src/pdfprism/core/types.py` — the data shapes services and UI pass
   around (`PageInfo`, `DocumentInfo`, `OutlineItem`, `SearchHit`,
   `CrossDocHit`).
3. `src/pdfprism/core/exceptions.py` — the error vocabulary.
4. `src/pdfprism/core/document.py` — the engine seam (read the docstrings).
5. `src/pdfprism/core/adapters/pymupdf_adapter.py` — the only file that
   knows what PyMuPDF looks like.
6. `src/pdfprism/services/search.py` — single-doc `find_all` and cross-doc
   `find_all_across`; the `SearchScope` enum.
7. `src/pdfprism/ui/page_cache.py` — the rendering choke point; everything
   that displays a page goes through here.
8. `src/pdfprism/ui/theme.py` — the dark-mode QSS stylesheet.
9. `src/pdfprism/ui/widgets/page_view.py` — the central page surface
   (zoom, navigation, view modes, signals, search highlights).
10. `src/pdfprism/ui/widgets/document_view.py` — the per-tab container;
    glues a page view to its sidebars and search service.
11. `src/pdfprism/ui/widgets/thumbnail_panel.py` — `QListView` thumbnails
    over the per-tab cache.
12. `src/pdfprism/ui/widgets/outline_panel.py` — `QTreeView` outline, with
    the stack-based flat-to-tree conversion.
13. `src/pdfprism/ui/widgets/search_bar.py` — find input, scope dropdown,
    counter, signals.
14. `src/pdfprism/ui/widgets/search_results_panel.py` — cross-doc results
    tree.
15. `src/pdfprism/ui/main_window.py` — tab management, dock frames,
    cross-search coordination, full-screen and dark theme, recent files
    and last-directory plumbing.
16. `src/pdfprism/app.py` — entry point and how everything wires together.
17. `tests/core/test_pymupdf_adapter.py` — the adapter contract.
18. `tests/services/test_search.py` — per-doc and cross-doc service-level
    expectations.
19. `tests/ui/test_document_view.py`, `test_main_window.py`,
    `test_search_results_panel.py`, `test_page_cache.py`,
    `test_page_view.py`, `test_thumbnail_panel.py`,
    `test_outline_panel.py`, `test_search_bar.py` — the UI surface, as
    assertions.

When adding a new feature, work bottom-up: extend the Protocol if needed,
implement in the adapter, add or extend a service, then wire it into the
UI.
