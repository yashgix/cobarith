"""cobarith: measure COBOL arithmetic against plausible Python translations."""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "upstream" / "carddemo" / "app"

__all__ = ["DATA_DIR"]
