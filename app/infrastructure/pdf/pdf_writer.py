from pathlib import Path
from typing import Iterable

import cv2
import fitz
import numpy as np


class PdfWriter:
    """Writes processed page images as a new PDF."""

    def write_from_images(self, images: Iterable[np.ndarray], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        for image in images:
            ok, encoded = cv2.imencode('.png', cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            if not ok:
                continue
            rect = fitz.Rect(0, 0, image.shape[1], image.shape[0])
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=encoded.tobytes())
        doc.save(output_path)
        doc.close()
