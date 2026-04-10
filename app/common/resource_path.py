"""Path helper compatible with PyInstaller bundles."""

from pathlib import Path
import sys


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative
