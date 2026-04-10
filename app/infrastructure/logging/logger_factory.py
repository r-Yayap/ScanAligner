import logging
from pathlib import Path

from app.config.constants import LOG_FILE_NAME


def configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eskan")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    file_handler = logging.FileHandler(log_dir / LOG_FILE_NAME, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger
