"""Application constants for Eskan."""

from pathlib import Path

APP_NAME = "Eskan"
APP_ORG = "InternalTools"
DEFAULT_OUTPUT_SUFFIX = "_normalized"
DEFAULT_MARGIN_RATIO = 0.06
DEFAULT_DPI = 180
LOG_FILE_NAME = "eskan.log"
SUPPORTED_EXTENSIONS = {".pdf"}
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "EskanOutput"
