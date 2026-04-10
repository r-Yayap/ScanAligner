from pathlib import Path
from typing import Iterable

from app.config.constants import SUPPORTED_EXTENSIONS


def expand_pdf_paths(items: Iterable[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in items:
        if item.is_dir():
            paths.extend(sorted(p for p in item.rglob("*.pdf") if p.is_file()))
        elif item.suffix.lower() in SUPPORTED_EXTENSIONS:
            paths.append(item)
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            result.append(rp)
    return result
