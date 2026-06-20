# PR 5 — View modes, full-screen, dark mode, recent files

Closes the Milestone 1 UX gap before multi-document tabs in PR 6.

## What's new

**View modes.** New `ViewMode` enum on `PageView` (`SINGLE_PAGE` and `CONTINUOUS`). Single-page is the default and behaves as before. Continuous mode lays out every page vertically with a fixed gutter, drives `current_page` from scroll position (topmost visible page wins), and renders highlights across every visible page that has hits. F3 across pages now scrolls the current hit into the viewport via a new `_ensure_hit_visible` helper. A `view_mode_changed(ViewMode)` signal closes the loop with the View menu's exclusive `QActionGroup`. Two-up "facing pages" and lazy on-scroll rendering are explicitly deferred to PR 5.5.

**Full-screen.** F11 toggles a distraction-free layout: menubar, both toolbars, status bar, and both docks hide; the window goes `showFullScreen`. Previous visibility of each chrome element is snapped into `_fullscreen_state` and restored on toggle-off (F11 again, or `Esc`). Every action that has a shortcut is now registered on `MainWindow` itself via `addAction(...)` so shortcuts survive the hidden menubar.

**Dark mode.** New `ui/theme.py` module with `DARK_QSS`, a Qt Style Sheet covering all visible chrome (menubar, menus, toolbars, status bar, docks, list/tree views, line edits, push buttons, scrollbars, tabs). `View → Dark Mode` is a checkable action persisted under `QSettings("view/dark_mode")` and restored at startup. The PDF page is rendered by PyMuPDF and is unaffected — only the chrome around it switches. No custom light QSS; light mode is the platform default.

**Recent files & last directory.** `File → Open Recent` submenu populated from `QSettings("recent/files")` (newline-joined, capped at `MAX_RECENT_FILES = 10` in `config.py`). `File → Open...` remembers the last successfully chosen directory under `QSettings("recent/last_dir")` and seeds the dialog with it on next invocation. `_on_open` (the dialog) is split from `_open_path` (the work) so the recent-files menu invokes the same code as a fresh open. `_open_path` canonicalizes via `Path.resolve(strict=False)` so different spellings of the same file collapse to one history entry.

**Failed-open recovery.** A new shared `_reset_to_empty_state` helper clears all UI surfaces (page view, sidebars, status bar, window title, action enablement). It's called from `File → Close` (which then closes the adapter) and from the `PdfPrismError` branch of `_open_path` (the adapter has already self-closed by then). Opening a non-PDF no longer leaves stale UI behind.

## Architecture decisions

- **One enum, two layouts.** `set_view_mode` rebuilds the scene via `_build_layout`, which dispatches to `_build_single_page_layout` or `_build_continuous_layout`. The scroll-driven `current_page` update is centralized in `_on_scroll`.
- **`view_mode_changed` signal even though MainWindow owns the menu.** It would have been simpler to set the menu checkmark directly when the menu fires. The signal exists so any future programmatic `set_view_mode` (e.g., restoring a per-document preference) keeps the menu in sync without an explicit caller-side update. The unit test asserts emission and payload.
- **No light QSS.** Custom light stylesheets fight with native Windows / macOS conventions. Light mode delegates to the platform; dark mode replaces the chrome wholesale.
- **`addAction(action)` loop after building all actions.** Without this, shortcuts only fire through the menu/toolbar, and full-screen (which hides them) silently breaks every keybinding. The loop registers all 22 actions on `MainWindow` itself, where Qt's shortcut delivery still finds them.
- **`Path.resolve(strict=False)` not `strict=True`.** A user may have an entry in Open Recent whose target was just deleted; we still want to attempt the open and surface the resulting error through the normal `PdfPrismError` channel rather than throwing inside the path normalization.
- **User-facing state via `QSettings`.** Three keys introduced: `view/dark_mode`, `recent/files`, `recent/last_dir`. Platform decides the backend (registry / plist / INI); the code only cares about the names. Added as a new Design Principle in `ARCHITECTURE.md`.

## Tests

- `tests/ui/test_page_view.py` grew from 17 to 25:
  - 7 `TestViewMode` cases covering default mode, single-page item count, continuous all-pages, switching back, pre-bind mode honored, continuous cross-page highlights, same-mode no-op
  - 1 signal test (`test_set_view_mode_emits_signal`) using `qtbot.waitSignal` to assert payload `[ViewMode.CONTINUOUS]`
- Total: 100 → 108 passing.

## Files

**New**
- `src/pdfprism/ui/theme.py` — `DARK_QSS` constant.

**Modified**
- `src/pdfprism/ui/widgets/page_view.py` — `ViewMode` enum, dual layouts, `_on_scroll`, `_ensure_hit_visible`, `view_mode_changed` signal.
- `src/pdfprism/ui/main_window.py` — full-screen with state save/restore, dark-mode toggle + `_apply_theme`, recent files submenu + load/save/add/clear/update helpers, last-dir seeding, `_on_open` / `_open_path` factoring, `_reset_to_empty_state`, `_on_view_mode_changed`, `addAction` loop for shortcut survival, `QMenu` import, `QKeyEvent` import + `keyPressEvent` for Esc-out-of-fullscreen.
- `tests/ui/test_page_view.py` — `TestViewMode` class.
- `docs/ARCHITECTURE.md` — View Modes, Theme, Full Screen, Recent Files sections; updated file tree; PR 5 roadmap entry filled in; QSS in glossary; theme.py added to reading order.
- `README.md` — Status through PR 5; new features bulleted; shortcuts table updated with Ctrl+3, Ctrl+4, F11, Esc.

## Deferred

- **PR 5.5:** Two-up / facing-pages view mode; lazy on-scroll rendering in continuous mode for very large documents.
- **PR 4.5 (still queued):** Case-sensitive, whole-word, and regex search; rotated-page highlight rect alignment via `Quad` + page rotation transform.

## Smoke tested

- Open `tests/fixtures/sample.pdf` → renders, title shows resolved path, recent files updates.
- Open the same file via Open Recent → opens, no duplicate entry.
- Open a non-PDF (`README.md`) → error dialog, UI fully resets, can immediately open a PDF after.
- Switch Single ↔ Continuous (Ctrl+3 / Ctrl+4) → scene rebuilds, page count and scroll behavior correct, menu checkmark tracks.
- F3 in continuous mode across pages → each hit lands in the visible viewport.
- F11 → chrome hides, shortcuts still work; F11 again → exact prior layout restored. Esc inside fullscreen also exits.
- Toggle dark mode → chrome restyles immediately, persists across app restart.
