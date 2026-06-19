"""Generate the test fixture PDF.

The output is committed to tests/fixtures/sample.pdf. Re-run only if the
fixture content needs updating.

Run with: uv run python scripts/generate_sample_pdf.py
"""

from pathlib import Path

import pymupdf


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output = project_root / "tests" / "fixtures" / "sample.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open()

    # Page 1 - US Letter, portrait
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Hello from pdfprism", fontsize=24)
    page.insert_text((72, 140), "Page 1 of 3", fontsize=14)

    # Page 2 - A4, portrait
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Page 2 of 3", fontsize=14)

    # Page 3 - A4 landscape with rotation metadata
    page = doc.new_page(width=842, height=595)
    page.set_rotation(90)
    page.insert_text((72, 100), "Page 3 of 3 (rotated 90)", fontsize=14)

    doc.set_metadata(
        {
            "title": "pdfprism sample",
            "author": "deswhk",
            "subject": "Test fixture",
            "keywords": "pdfprism, test, fixture",
            "creator": "scripts/generate_sample_pdf.py",
        }
    )

    doc.save(str(output), garbage=4, deflate=True, clean=True)
    doc.close()

    print(f"Wrote: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
