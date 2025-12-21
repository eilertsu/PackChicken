"""
packchicken.utils.pdf

Kun sammenslåing av ekte Bring-PDF-er (ingen mock-etiketter genereres).
"""

from pathlib import Path
from pypdf import PdfReader, PdfWriter


def combine_pdfs(input_paths: list[Path], output_path: Path) -> Path:
    """
    Slår sammen flere PDF-filer til én.
    """
    writer = PdfWriter()
    for path in input_paths:
        if not Path(path).exists():
            continue
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as fh:
        writer.write(fh)
    return output_path
