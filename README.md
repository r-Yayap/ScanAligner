# Eskan

Eskan is a PySide6 desktop application for normalizing scanned PDF pages before OCR/text extraction.

## Highlights
- Drag/drop PDF files or folders.
- Preview original vs processed pages.
- OpenCV-based border cleanup, crop estimation, deskew, and margin normalization.
- Batch processing with progress and cancellation using QThread + QObject worker.
- Structured architecture (UI/presentation/application/domain/infrastructure).

## Processing strategy
1. Render page with PyMuPDF at configured DPI.
2. Convert to grayscale and detect foreground with inverse threshold.
3. Compute content bounding box from non-background pixels.
4. Trim dark scanner edges using a low-intensity mask around content.
5. Estimate skew via Hough line angle median.
6. Crop and optional deskew.
7. Compute a batch-wide canonical page size and reference content box.
8. Optionally detect a title block rectangle from scanned content and lock it to a stable anchor point.
9. Fit every page on the standardized canvas with configured margin ratio and anchor.
10. Write processed pages back to output PDF.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

## Tests
```bash
pytest -q
```

## Packaging
```bash
pyinstaller Eskan.spec
```
