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
8. Optionally detect a title block rectangle from scanned content, preview its overlay, and lock it to a stable anchor point.
9. Fit every page on the standardized canvas with configured margin ratio and anchor.
10. Write processed pages back to output PDF.

In `outer_frame` mode, frame reference can be taken from the **first confident page** (default) or from a median consensus across the document.
You can also export per-page frame-debug artifacts (`rectified`, `bw_mask`, `frame_overlay`, `canvas_preview`) to inspect clipping/detection issues.

## Run the desktop app
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

You can also run:
```bash
python app/main.py
```

## Title block template aligner (GUI-integrated)
Title block template alignment is available directly in the desktop app:
- enable **Detect title block**
- choose one template source:
  - **Upload template file** with **Title block template** (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, or `.pdf` where first page is used)
  - **Use selected block as template** after drawing a title-block selection on the preview page
- run preview/processing as usual

If both are provided, the uploaded template image is used first.

The CLI remains available for debugging and experimentation:
Run it with:
```bash
python -m app.infrastructure.imaging.title_block_template_aligner \
  --template path/to/titleblock_template.png \
  --scan path/to/scanned_page.png \
  --out-prefix out/page01
```

This writes:
- `out/page01_detected_titleblock.png`
- `out/page01_aligned_scan.png`
- `out/page01_matches.png`

## Tests
```bash
pytest -q
```

## Packaging
```bash
pyinstaller Eskan.spec
```
