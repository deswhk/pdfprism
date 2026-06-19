"""pytest configuration and shared fixtures."""

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
def garbage_file(tmp_path: Path) -> Path:
    """A file with .pdf extension that is not a valid PDF."""
    path = tmp_path / "garbage.pdf"
    path.write_text("This is not a PDF file.")
    return path


@pytest.fixture
def missing_pdf_path(tmp_path: Path) -> Path:
    """A path that does not exist."""
    return tmp_path / "does_not_exist.pdf"
