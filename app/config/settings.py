"""Typed configuration models."""

from dataclasses import dataclass
from pathlib import Path

from app.config.constants import DEFAULT_DPI, DEFAULT_MARGIN_RATIO, DEFAULT_OUTPUT_DIR, DEFAULT_OUTPUT_SUFFIX
from app.domain.enums.page_size_mode import PageSizeMode


@dataclass(slots=True)
class ProcessingSettings:
    auto_crop_borders: bool = True
    deskew: bool = True
    remove_dark_edges: bool = True
    normalize_margins: bool = True
    page_size_mode: PageSizeMode = PageSizeMode.PRESERVE_DOMINANT
    content_threshold: int = 205
    edge_dark_threshold: int = 40
    margin_ratio: float = DEFAULT_MARGIN_RATIO
    content_anchor: str = "bottom_right"
    detect_title_block: bool = True
    render_dpi: int = DEFAULT_DPI
    output_suffix: str = DEFAULT_OUTPUT_SUFFIX
    output_dir: Path = DEFAULT_OUTPUT_DIR
    overwrite: bool = False
