from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import configparser
import sys


APP_NAME = "Escanor"
CONFIG_FILENAME = "escanor_settings.ini"


@dataclass
class EscanorSettings:
    input_path: str = ""
    output_path: str = ""
    template_path: str = ""
    recursive: bool = False

    page_size: str = "A1"
    mode: str = "outer_frame"
    orientation: str = "landscape"
    dpi: int = 150
    output_color_mode: str = "color"

    content_margin_mm: float = 10.0
    canvas_margin_mm: float = 3.0

    page_placement: str = "fill"
    page_anchor: str = "BR"

    use_document_frame_consensus: bool = True
    reject_paper_edge_frames: bool = True
    use_black_white_for_frame_detection: bool = True
    use_shared_bw_corner_lock: bool = True


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    return app_root() / CONFIG_FILENAME


def _bool(value: str, fallback: bool) -> bool:
    if value is None:
        return fallback
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return fallback


def _int(value: str, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return fallback


def _float(value: str, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return fallback


def ensure_config_exists(path: Path | None = None) -> Path:
    target = path or default_config_path()
    if not target.exists():
        target.write_text(render_config_template(EscanorSettings()), encoding="utf-8")
    return target


def load_settings(path: Path | None = None) -> EscanorSettings:
    target = ensure_config_exists(path)
    parser = configparser.ConfigParser()
    parser.read(target, encoding="utf-8")

    settings = EscanorSettings()

    if parser.has_section("paths"):
        section = parser["paths"]
        settings.input_path = section.get("input_path", settings.input_path)
        settings.output_path = section.get("output_path", settings.output_path)
        settings.template_path = section.get("template_path", settings.template_path)
        settings.recursive = _bool(section.get("recursive"), settings.recursive)

    if parser.has_section("processing"):
        section = parser["processing"]
        settings.page_size = section.get("page_size", settings.page_size)
        settings.mode = section.get("mode", settings.mode)
        settings.orientation = section.get("orientation", settings.orientation)
        settings.dpi = _int(section.get("dpi"), settings.dpi)
        settings.output_color_mode = section.get("output_color_mode", settings.output_color_mode)
        settings.content_margin_mm = _float(section.get("content_margin_mm"), settings.content_margin_mm)
        settings.canvas_margin_mm = _float(section.get("canvas_margin_mm"), settings.canvas_margin_mm)
        settings.page_placement = section.get("page_placement", settings.page_placement)
        settings.page_anchor = section.get("page_anchor", settings.page_anchor)
        settings.use_document_frame_consensus = _bool(
            section.get("use_document_frame_consensus"), settings.use_document_frame_consensus
        )
        settings.reject_paper_edge_frames = _bool(
            section.get("reject_paper_edge_frames"), settings.reject_paper_edge_frames
        )
        settings.use_black_white_for_frame_detection = _bool(
            section.get("use_black_white_for_frame_detection"), settings.use_black_white_for_frame_detection
        )
        settings.use_shared_bw_corner_lock = _bool(
            section.get("use_shared_bw_corner_lock"), settings.use_shared_bw_corner_lock
        )

    return settings


def save_settings(settings: EscanorSettings, path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.write_text(render_config_template(settings), encoding="utf-8")
    return target


def render_config_template(settings: EscanorSettings) -> str:
    return f"""# Escanor configuration file
# ----------------------------------------------------------------------
# Edit this file in a text editor if you want to change the default values
# that appear in the GUI when Escanor starts.
#
# Quick guidance:
# - input_path:
#     Leave blank if you prefer to browse in the GUI.
#     You can set a single PDF file path or a folder path.
# - output_path:
#     For a single input PDF, this can be a single output PDF path.
#     For a folder input, this should normally be an output folder.
# - template_path:
#     Optional. Mainly useful in content mode.
# - mode:
#     page | outer_frame | content
# - orientation:
#     auto | landscape | portrait
# - output_color_mode:
#     color | grayscale | black_white
# - page_placement:
#     fill | balanced
# - page_anchor:
#     TL | TR | BL | BR | C
#
# Practical starting defaults for engineering scans:
# - mode = outer_frame
# - orientation = landscape
# - dpi = 150
# - output_color_mode = color
# - page_anchor = BR
# - use_document_frame_consensus = true
# - reject_paper_edge_frames = true
# - use_black_white_for_frame_detection = true

[paths]
input_path = {settings.input_path}
output_path = {settings.output_path}
template_path = {settings.template_path}
recursive = {"true" if settings.recursive else "false"}

[processing]
page_size = {settings.page_size}
mode = {settings.mode}
orientation = {settings.orientation}
dpi = {settings.dpi}
output_color_mode = {settings.output_color_mode}
content_margin_mm = {settings.content_margin_mm}
canvas_margin_mm = {settings.canvas_margin_mm}
page_placement = {settings.page_placement}
page_anchor = {settings.page_anchor}
use_document_frame_consensus = {"true" if settings.use_document_frame_consensus else "false"}
reject_paper_edge_frames = {"true" if settings.reject_paper_edge_frames else "false"}
use_black_white_for_frame_detection = {"true" if settings.use_black_white_for_frame_detection else "false"}
use_shared_bw_corner_lock = {"true" if settings.use_shared_bw_corner_lock else "false"}
"""
