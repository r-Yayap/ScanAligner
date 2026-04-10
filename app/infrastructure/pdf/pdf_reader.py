from pathlib import Path

import fitz
import numpy as np

from app.common.exceptions.app_exceptions import PdfProcessingError


class PdfPageRenderer:
    """Renders PDF pages to OpenCV-ready ndarray images."""

    def open_document(self, path: Path) -> fitz.Document:
        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise PdfProcessingError(f"Cannot open PDF: {path}") from exc
        if doc.needs_pass:
            raise PdfProcessingError(f"Password-protected PDF unsupported: {path}")
        if doc.page_count == 0:
            raise PdfProcessingError(f"Empty PDF: {path}")
        return doc

    def render_page_rgb(self, page: fitz.Page, dpi: int) -> np.ndarray:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8)
        return arr.reshape((pix.height, pix.width, pix.n))
