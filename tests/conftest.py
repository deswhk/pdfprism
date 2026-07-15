"""pytest configuration and shared fixtures."""

import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pdf_path() -> Path:
    """Path to the committed sample PDF fixture."""
    path = FIXTURES_DIR / "sample.pdf"
    assert path.exists(), (
        f"Missing fixture: {path}. Run: uv run python scripts/generate_sample_pdf.py"
    )
    return path


@pytest.fixture
def mutable_pdf_path(sample_pdf_path: Path, tmp_path: Path) -> Path:
    """Writable copy of sample.pdf for mutation tests.

    The committed sample.pdf is intentionally treated as read-only --
    PR 8 page-operation tests need a copy they can rotate, delete from,
    crop, save over, and reopen without polluting the fixture or other
    tests. Copies on every request because pytest's tmp_path is unique
    per-test.
    """
    dst = tmp_path / "mutable.pdf"
    shutil.copy(sample_pdf_path, dst)
    return dst


@pytest.fixture
def garbage_file(tmp_path: Path) -> Path:
    """A file with .pdf extension that is not a valid PDF."""
    path = tmp_path / "garbage.pdf"
    path.write_text("This is not a PDF file.")
    return path


@pytest.fixture
def missing_pdf_path(tmp_path: Path) -> Path:
    """A path that does not exist."""
    return tmp_path / "does_not_exist.pdf"


# ---- Encrypted PDF fixtures (PR 10) ------------------------------------

ENCRYPTED_PDF_PASSWORD = "hunter2"


@pytest.fixture(scope="session")
def _encrypted_pdf_bytes() -> bytes:
    """One-time generation of an encrypted PDF's bytes.

    Uses PyMuPDF's own encryption facilities: creates a 1-page in-memory
    doc, saves with AES-256 encryption and user password ``hunter2``,
    returns the resulting bytes. Session-scoped because the bytes never
    change; ``encrypted_pdf_path`` writes them to a fresh tmp file per
    test so mutation tests can't cross-contaminate.
    """
    import pymupdf

    doc = pymupdf.open()  # empty doc
    try:
        doc.new_page(width=200, height=200)
        # PDF_ENCRYPT_AES_256 is the strongest standard-handler option.
        # user_pw locks opening; owner_pw locks permission changes.
        # For PR 10 we only care about the user password path.
        return doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=ENCRYPTED_PDF_PASSWORD,
            owner_pw="",
        )
    finally:
        doc.close()


@pytest.fixture
def encrypted_pdf_path(_encrypted_pdf_bytes: bytes, tmp_path: Path) -> Path:
    """Per-test encrypted PDF file at ``tmp_path/encrypted.pdf``.

    The password to open it is ``ENCRYPTED_PDF_PASSWORD`` (module-level
    constant, defined alongside this fixture).
    """
    path = tmp_path / "encrypted.pdf"
    path.write_bytes(_encrypted_pdf_bytes)
    return path
