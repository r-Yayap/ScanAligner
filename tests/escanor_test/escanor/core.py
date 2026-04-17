#!/usr/bin/env python3
"""
escanor/core.py

Escanor core engine for scanned PDF normalization.

What changed in v6:
- improves outer_frame detection so it prefers lines near the true page margins
- adds document-level frame consensus for multi-page PDFs
- outlier pages can snap to the document median frame rectangle for stronger batch consistency
- keeps the older fallback path when a frame cannot be confidently detected

Modes:
1) page
   Normalize the full sheet onto a fixed A-size canvas.
   Page placement options:
   - fill: rectify -> anchor-aware whitespace crop -> stretch fill target box
   - balanced: rectify -> anchor-aware whitespace crop -> fit proportionally -> align inside target box

2) content
   Crop to the actual content and place it on a fixed canvas.

3) outer_frame
   Rectify the page, detect the printed outer frame, then scale/translate the whole page so that
   the detected frame rectangle lands on a fixed target rectangle on the chosen ISO canvas.

Requirements:
    pip install pymupdf opencv-python numpy

New in v10:
- uses one shared black-and-white mask for both outer-frame detection and final black_white export
- locks the detected bottom-right frame corner using the same mask the user sees in black_white output
- improves consistency for sparse sheets where the visible BR corner was not the same geometry used during alignment
- keeps document consensus, paper-edge rejection, and output color modes
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np


ISO_SIZES_MM = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A3": (297, 420),
    "A4": (210, 297),
}
ANCHOR_CHOICES = ["TL", "TR", "BL", "BR", "C"]


def mm_to_px(mm: float, dpi: int) -> int:
    return max(1, int(round(mm / 25.4 * dpi)))


def page_size_px(page_size: str, dpi: int, landscape: bool = False) -> Tuple[int, int]:
    w_mm, h_mm = ISO_SIZES_MM[page_size.upper()]
    w_px = mm_to_px(w_mm, dpi)
    h_px = mm_to_px(h_mm, dpi)
    if landscape:
        return h_px, w_px
    return w_px, h_px


def list_input_pdfs(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted(input_path.glob(pattern))
    raise FileNotFoundError(f"Input path not found or not a PDF: {input_path}")


def render_pdf_page_to_bgr(page: fitz.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def read_image_unicode(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read image template: {path}")
    return img


def load_template_image(template_path: Path, dpi: int) -> np.ndarray:
    if template_path.suffix.lower() == ".pdf":
        doc = fitz.open(template_path)
        try:
            if doc.page_count == 0:
                raise ValueError("Template PDF has no pages.")
            return render_pdf_page_to_bgr(doc.load_page(0), dpi=dpi)
        finally:
            doc.close()
    return read_image_unicode(template_path)


def resize_for_detection(image: np.ndarray, max_side: int = 1800) -> Tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(max_side / max(h, w), 1.0)
    if scale == 1.0:
        return image.copy(), 1.0
    resized = cv2.resize(
        image,
        (int(round(w * scale)), int(round(h * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def order_points(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)

    top_left = pts[np.argmin(s)]
    bottom_right = pts[np.argmax(s)]
    top_right = pts[np.argmin(diff)]
    bottom_left = pts[np.argmax(diff)]

    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)

    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])

    new_w = int(round((h * sin) + (w * cos)))
    new_h = int(round((h * cos) + (w * sin)))

    M[0, 2] += (new_w / 2.0) - center[0]
    M[1, 2] += (new_h / 2.0) - center[1]

    return cv2.warpAffine(
        image,
        M,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def estimate_skew_angle(image: np.ndarray, max_abs_angle: float = 12.0) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(inv > 0))
    if len(coords) < 200:
        return 0.0

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    angle = -float(angle)

    if abs(angle) > max_abs_angle:
        return 0.0
    return angle


def detect_page_quad(image: np.ndarray) -> Optional[np.ndarray]:
    small, scale = resize_for_detection(image, max_side=1800)
    h, w = small.shape[:2]
    total_area = float(h * w)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8), iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < total_area * 0.35:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2)
        else:
            quad = cv2.boxPoints(cv2.minAreaRect(c))
        candidates.append((area, quad))

    if candidates:
        area, quad = max(candidates, key=lambda item: item[0])
        if total_area * 0.35 <= area <= total_area * 0.995:
            return quad.astype(np.float32) / scale

    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < total_area * 0.35:
            continue
        quad = cv2.boxPoints(cv2.minAreaRect(c))
        candidates.append((area, quad))

    if candidates:
        area, quad = max(candidates, key=lambda item: item[0])
        if total_area * 0.35 <= area <= total_area * 0.995:
            return quad.astype(np.float32) / scale

    return None


def detect_content_bbox(image: np.ndarray, extra_padding_ratio: float = 0.01) -> Tuple[int, int, int, int]:
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    edge_strip = max(2, int(round(min(h, w) * 0.006)))
    gray = gray.copy()
    gray[:edge_strip, :] = 255
    gray[-edge_strip:, :] = 255
    gray[:, :edge_strip] = 255
    gray[:, -edge_strip:] = 255

    _, inv = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
    inv = cv2.morphologyEx(inv, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    inv = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h * w * 0.00002
    boxes = []

    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue

        x, y, bw, bh = cv2.boundingRect(c)

        if bw > w * 0.85 and bh < max(6, h * 0.01):
            continue
        if bh > h * 0.85 and bw < max(6, w * 0.01):
            continue

        touches_edge = x <= 1 or y <= 1 or (x + bw) >= (w - 1) or (y + bh) >= (h - 1)
        if touches_edge and area < (h * w * 0.002):
            continue

        boxes.append((x, y, bw, bh))

    if not boxes:
        return 0, 0, w, h

    x0 = min(x for x, _, _, _ in boxes)
    y0 = min(y for _, y, _, _ in boxes)
    x1 = max(x + bw for x, _, bw, _ in boxes)
    y1 = max(y + bh for _, y, _, bh in boxes)

    pad = int(round(extra_padding_ratio * max(w, h)))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)

    if x1 <= x0 or y1 <= y0:
        return 0, 0, w, h

    return x0, y0, x1 - x0, y1 - y0



def _moving_average_1d(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.astype(np.float32, copy=False)
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(values.astype(np.float32), kernel, mode="same")


def make_shared_black_white_output(image: np.ndarray) -> np.ndarray:
    """
    Build the canonical black-and-white representation used for both detection and
    final black_white export when possible. This keeps the visible frame/corner
    closer to the exact geometry used for alignment.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.medianBlur(bw, 3)
    return bw


def make_shared_ink_mask(image: np.ndarray) -> np.ndarray:
    """Return a binary mask where ink / lines are white (255)."""
    return cv2.bitwise_not(make_shared_black_white_output(image))


def make_frame_detection_mask(image: np.ndarray, use_black_white: bool = True) -> np.ndarray:
    """
    Build a binary ink mask for frame detection.

    When use_black_white is True, use the same shared B/W export mask so the
    frame the user sees in final black_white output is much closer to the frame
    geometry used during detection and alignment.
    """
    if use_black_white:
        return make_shared_ink_mask(image)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    _, inv = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)
    return inv


def _resize_mask(mask: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return mask.copy()
    h, w = mask.shape[:2]
    return cv2.resize(mask, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_NEAREST)


def _detect_outer_frame_bbox_union(
    image: np.ndarray,
    use_black_white: bool = True,
    ink_mask: Optional[np.ndarray] = None,
) -> Optional[Tuple[int, int, int, int]]:
    small, scale = resize_for_detection(image, max_side=1800)
    h, w = small.shape[:2]

    if ink_mask is not None:
        inv = _resize_mask(ink_mask, scale)
    else:
        inv = make_frame_detection_mask(small, use_black_white=use_black_white)

    edge_strip = max(2, int(round(min(h, w) * 0.004)))
    inv = inv.copy()
    inv[:edge_strip, :] = 0
    inv[-edge_strip:, :] = 0
    inv[:, :edge_strip] = 0
    inv[:, -edge_strip:] = 0

    h_kernel = max(30, w // 12)
    v_kernel = max(30, h // 12)
    horiz = cv2.morphologyEx(
        inv,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel, 1)),
    )
    vert = cv2.morphologyEx(
        inv,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel)),
    )
    combined = cv2.bitwise_or(horiz, vert)
    combined = cv2.morphologyEx(
        combined,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
        iterations=1,
    )

    ys, xs = np.where(combined > 0)
    if len(xs) == 0:
        return None

    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1

    bw = x1 - x0
    bh = y1 - y0
    if bw < w * 0.55 or bh < h * 0.55:
        return None

    x0 = int(round(x0 / scale))
    y0 = int(round(y0 / scale))
    bw = int(round(bw / scale))
    bh = int(round(bh / scale))

    H, W = image.shape[:2]
    x0 = int(np.clip(x0, 0, max(0, W - 2)))
    y0 = int(np.clip(y0, 0, max(0, H - 2)))
    bw = int(np.clip(bw, 1, W - x0))
    bh = int(np.clip(bh, 1, H - y0))
    return x0, y0, bw, bh


def _edge_strength(gray: np.ndarray, x: int, y: int, bw: int, bh: int) -> Tuple[int, int, int, int]:

    h, w = gray.shape[:2]
    strip = max(2, int(round(min(h, w) * 0.0025)))

    def darkness(region: np.ndarray) -> float:
        if region.size == 0:
            return 0.0
        return float(255.0 - region.mean())

    top_in = darkness(gray[max(0, y):min(h, y + strip), max(0, x):min(w, x + bw)])
    bot_in = darkness(gray[max(0, y + bh - strip):min(h, y + bh), max(0, x):min(w, x + bw)])
    left_in = darkness(gray[max(0, y):min(h, y + bh), max(0, x):min(w, x + strip)])
    right_in = darkness(gray[max(0, y):min(h, y + bh), max(0, x + bw - strip):min(w, x + bw)])

    top_out = darkness(gray[max(0, y - strip):max(0, y), max(0, x):min(w, x + bw)])
    bot_out = darkness(gray[min(h, y + bh):min(h, y + bh + strip), max(0, x):min(w, x + bw)])
    left_out = darkness(gray[max(0, y):min(h, y + bh), max(0, x - strip):max(0, x)])
    right_out = darkness(gray[max(0, y):min(h, y + bh), min(w, x + bw):min(w, x + bw + strip)])

    edge_hits = 0
    for inside, outside in ((top_in, top_out), (bot_in, bot_out), (left_in, left_out), (right_in, right_out)):
        if inside >= outside + 8.0 and inside >= 10.0:
            edge_hits += 1

    return edge_hits, int(round(top_in)), int(round(bot_in)), int(round(max(left_in, right_in)))


def validate_outer_frame_candidate(
    image: np.ndarray,
    bbox: Optional[Tuple[int, int, int, int]],
    base_confidence: float,
    reject_paper_edge_frames: bool = True,
) -> Tuple[Optional[Tuple[int, int, int, int]], float]:
    if bbox is None:
        return None, 0.0
    if not reject_paper_edge_frames:
        return bbox, base_confidence

    h, w = image.shape[:2]
    x, y, bw, bh = bbox
    if bw <= 0 or bh <= 0:
        return None, 0.0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    insets = [x, y, w - (x + bw), h - (y + bh)]
    min_dim = float(min(h, w))
    near_edge_thresh = max(3, int(round(min_dim * 0.004)))
    definite_inset_thresh = max(8, int(round(min_dim * 0.012)))
    near_edge_count = sum(v <= near_edge_thresh for v in insets)
    inset_count = sum(v >= definite_inset_thresh for v in insets)
    area_ratio = (bw * bh) / float(max(1, w * h))

    edge_hits, top_dark, bottom_dark, side_dark = _edge_strength(gray, x, y, bw, bh)

    # Case 1: almost full-page candidate hugging the page boundary with weak frame evidence.
    if area_ratio >= 0.975 and near_edge_count >= 2 and edge_hits <= 2:
        return None, 0.0

    # Case 2: likely the paper edge rather than an inset printed frame.
    if near_edge_count >= 3 and inset_count == 0 and edge_hits <= 2:
        return None, 0.0

    # Case 3: weak or missing frame - large union box but little real border contrast.
    if base_confidence < 0.45 and edge_hits <= 1:
        return None, 0.0

    # Penalize suspicious edge-hugging candidates so document consensus can override them.
    adjusted = float(base_confidence)
    if near_edge_count >= 2 and inset_count <= 1:
        adjusted *= 0.55
    if edge_hits == 2:
        adjusted *= 0.8

    return bbox, adjusted


def detect_outer_frame_bbox_with_confidence(
    image: np.ndarray,
    reject_paper_edge_frames: bool = True,
    use_black_white: bool = True,
    ink_mask: Optional[np.ndarray] = None,
) -> Tuple[Optional[Tuple[int, int, int, int]], float]:
    """
    Detect the printed outer frame after page rectification.

    In v10 this can use a precomputed shared ink mask so outer-frame detection
    is based on the same B/W geometry later used for black_white output.
    """
    small, scale = resize_for_detection(image, max_side=1800)
    h, w = small.shape[:2]

    if ink_mask is not None:
        inv = _resize_mask(ink_mask, scale)
    else:
        inv = make_frame_detection_mask(small, use_black_white=use_black_white)

    edge_strip = max(2, int(round(min(h, w) * 0.004)))
    inv = inv.copy()
    inv[:edge_strip, :] = 0
    inv[-edge_strip:, :] = 0
    inv[:, :edge_strip] = 0
    inv[:, -edge_strip:] = 0

    h_kernel = max(40, w // 14)
    v_kernel = max(40, h // 14)
    horiz = cv2.morphologyEx(
        inv,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel, 1)),
    )
    vert = cv2.morphologyEx(
        inv,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel)),
    )

    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, w // 180), 1)), iterations=1)
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, h // 180))), iterations=1)

    row_support = _moving_average_1d((horiz > 0).sum(axis=1), max(3, h // 250))
    col_support = _moving_average_1d((vert > 0).sum(axis=0), max(3, w // 250))

    min_row_support = w * 0.15
    min_col_support = h * 0.15

    top_band_end = max(edge_strip + 5, int(round(h * 0.24)))
    bottom_band_start = min(h - edge_strip - 5, int(round(h * 0.70)))
    left_band_end = max(edge_strip + 5, int(round(w * 0.24)))
    right_band_start = min(w - edge_strip - 5, int(round(w * 0.70)))

    def first_support_index(arr: np.ndarray, start: int, end: int, threshold: float) -> Optional[int]:
        end = min(len(arr), max(start + 1, end))
        idxs = np.where(arr[start:end] >= threshold)[0]
        if len(idxs) == 0:
            return None
        return int(start + idxs[0])

    def last_support_index(arr: np.ndarray, start: int, end: int, threshold: float) -> Optional[int]:
        end = min(len(arr), max(start + 1, end))
        idxs = np.where(arr[start:end] >= threshold)[0]
        if len(idxs) == 0:
            return None
        return int(start + idxs[-1])

    top = first_support_index(row_support, edge_strip + 1, top_band_end, min_row_support)
    bottom = last_support_index(row_support, bottom_band_start, h - edge_strip - 1, min_row_support)
    left = first_support_index(col_support, edge_strip + 1, left_band_end, min_col_support)
    right = last_support_index(col_support, right_band_start, w - edge_strip - 1, min_col_support)

    if None not in (top, bottom, left, right):
        x0, y0 = int(left), int(top)
        x1, y1 = int(right) + 1, int(bottom) + 1
        bw, bh = x1 - x0, y1 - y0

        if bw >= w * 0.80 and bh >= h * 0.80:
            confidences = [
                min(1.0, float(row_support[top]) / max(1.0, w * 0.55)),
                min(1.0, float(row_support[bottom]) / max(1.0, w * 0.55)),
                min(1.0, float(col_support[left]) / max(1.0, h * 0.55)),
                min(1.0, float(col_support[right]) / max(1.0, h * 0.55)),
            ]
            confidence = float(np.mean(confidences))

            x0 = int(round(x0 / scale))
            y0 = int(round(y0 / scale))
            x1 = int(round(x1 / scale))
            y1 = int(round(y1 / scale))
            H, W = image.shape[:2]
            x0 = int(np.clip(x0, 0, max(0, W - 2)))
            y0 = int(np.clip(y0, 0, max(0, H - 2)))
            x1 = int(np.clip(x1, x0 + 1, W))
            y1 = int(np.clip(y1, y0 + 1, H))
            return validate_outer_frame_candidate(image, (x0, y0, x1 - x0, y1 - y0), confidence, reject_paper_edge_frames=reject_paper_edge_frames)

    fallback = _detect_outer_frame_bbox_union(image, use_black_white=use_black_white, ink_mask=ink_mask)
    if fallback is None:
        return None, 0.0
    return validate_outer_frame_candidate(image, fallback, 0.35, reject_paper_edge_frames=reject_paper_edge_frames)


def detect_outer_frame_bbox(image: np.ndarray, use_black_white: bool = True, ink_mask: Optional[np.ndarray] = None) -> Optional[Tuple[int, int, int, int]]:
    bbox, _ = detect_outer_frame_bbox_with_confidence(image, use_black_white=use_black_white, ink_mask=ink_mask)
    return bbox


def warp_quad_to_rect(image: np.ndarray, quad: np.ndarray, out_w: int, out_h: int) -> np.ndarray:

    rect = order_points(quad)
    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(
        image,
        M,
        (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def fit_image_into_box(content_img: np.ndarray, box_w: int, box_h: int) -> np.ndarray:
    src_h, src_w = content_img.shape[:2]
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Invalid content image size during fitting.")

    scale = min(box_w / src_w, box_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    interpolation = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(content_img, (new_w, new_h), interpolation=interpolation)


def infer_rectified_page_size(quad: np.ndarray) -> Tuple[int, int]:
    rect = order_points(quad)
    width_top = np.linalg.norm(rect[1] - rect[0])
    width_bottom = np.linalg.norm(rect[2] - rect[3])
    height_left = np.linalg.norm(rect[3] - rect[0])
    height_right = np.linalg.norm(rect[2] - rect[1])
    out_w = max(1, int(round(max(width_top, width_bottom))))
    out_h = max(1, int(round(max(height_left, height_right))))
    return out_w, out_h


def anchor_to_axes(anchor: str) -> Tuple[str, str]:
    anchor = anchor.upper()
    if anchor == "TL":
        return "left", "top"
    if anchor == "TR":
        return "right", "top"
    if anchor == "BL":
        return "left", "bottom"
    if anchor == "BR":
        return "right", "bottom"
    return "center", "center"


def crop_to_anchor_margins(
    image: np.ndarray,
    anchor_bbox: Tuple[int, int, int, int],
    anchor: str,
    tolerance_px: int = 2,
) -> np.ndarray:
    """
    Trim whitespace around the detected anchor box according to the selected anchor.

    TL: crop left/top whitespace first so visible content/frame biases to top-left.
    BR: crop right/bottom whitespace first so visible content/frame biases to bottom-right.
    C:  crop the larger side on each axis so the content/frame becomes centered.
    """
    h, w = image.shape[:2]
    x, y, bw, bh = anchor_bbox

    left = max(0, x)
    right = max(0, w - (x + bw))
    top = max(0, y)
    bottom = max(0, h - (y + bh))

    horiz, vert = anchor_to_axes(anchor)

    if horiz == "center":
        crop_left = max(0, left - right) if left > right + tolerance_px else 0
        crop_right = max(0, right - left) if right > left + tolerance_px else 0
    elif horiz == "left":
        crop_left = left
        crop_right = 0
    else:  # right
        crop_left = 0
        crop_right = right

    if vert == "center":
        crop_top = max(0, top - bottom) if top > bottom + tolerance_px else 0
        crop_bottom = max(0, bottom - top) if bottom > top + tolerance_px else 0
    elif vert == "top":
        crop_top = top
        crop_bottom = 0
    else:  # bottom
        crop_top = 0
        crop_bottom = bottom

    x0 = int(np.clip(crop_left, 0, max(0, w - 2)))
    x1 = int(np.clip(w - crop_right, x0 + 1, w))
    y0 = int(np.clip(crop_top, 0, max(0, h - 2)))
    y1 = int(np.clip(h - crop_bottom, y0 + 1, h))

    return image[y0:y1, x0:x1]


def place_image_aligned(
    canvas: np.ndarray,
    image: np.ndarray,
    target_x: int,
    target_y: int,
    target_w: int,
    target_h: int,
    anchor: str,
) -> None:
    placed = fit_image_into_box(image, target_w, target_h)
    ph, pw = placed.shape[:2]
    horiz, vert = anchor_to_axes(anchor)

    if horiz == "left":
        paste_x = target_x
    elif horiz == "right":
        paste_x = target_x + max(0, target_w - pw)
    else:
        paste_x = target_x + max(0, (target_w - pw) // 2)

    if vert == "top":
        paste_y = target_y
    elif vert == "bottom":
        paste_y = target_y + max(0, target_h - ph)
    else:
        paste_y = target_y + max(0, (target_h - ph) // 2)

    paste_x2 = min(canvas.shape[1], paste_x + pw)
    paste_y2 = min(canvas.shape[0], paste_y + ph)
    canvas[paste_y:paste_y2, paste_x:paste_x2] = placed[: paste_y2 - paste_y, : paste_x2 - paste_x]


def paste_image_with_offset(canvas: np.ndarray, image: np.ndarray, paste_x: int, paste_y: int) -> None:
    canvas_h, canvas_w = canvas.shape[:2]
    img_h, img_w = image.shape[:2]

    dst_x0 = max(0, paste_x)
    dst_y0 = max(0, paste_y)
    dst_x1 = min(canvas_w, paste_x + img_w)
    dst_y1 = min(canvas_h, paste_y + img_h)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return

    src_x0 = max(0, -paste_x)
    src_y0 = max(0, -paste_y)
    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    canvas[dst_y0:dst_y1, dst_x0:dst_x1] = image[src_y0:src_y1, src_x0:src_x1]


def rectify_page_image(image: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    angle = estimate_skew_angle(image)
    if angle:
        image = rotate_bound(image, angle)

    quad = detect_page_quad(image)
    if quad is None:
        return image, None

    out_w, out_h = infer_rectified_page_size(quad)
    rectified = warp_quad_to_rect(image, quad, out_w, out_h)
    return rectified, quad


def compute_template_content_fractions(template_image: np.ndarray) -> Tuple[float, float, float, float]:
    template_image, _ = rectify_page_image(template_image)
    x, y, w, h = detect_content_bbox(template_image)
    H, W = template_image.shape[:2]
    return x / W, y / H, w / W, h / H


def bbox_to_fractions(bbox: Tuple[int, int, int, int], image_w: int, image_h: int) -> Tuple[float, float, float, float]:
    x, y, w, h = bbox
    return x / image_w, y / image_h, (x + w) / image_w, (y + h) / image_h


def fractions_to_bbox(
    fractions: Tuple[float, float, float, float],
    image_w: int,
    image_h: int,
) -> Tuple[int, int, int, int]:
    fx0, fy0, fx1, fy1 = fractions
    x0 = int(round(fx0 * image_w))
    y0 = int(round(fy0 * image_h))
    x1 = int(round(fx1 * image_w))
    y1 = int(round(fy1 * image_h))
    x0 = int(np.clip(x0, 0, max(0, image_w - 2)))
    y0 = int(np.clip(y0, 0, max(0, image_h - 2)))
    x1 = int(np.clip(x1, x0 + 1, image_w))
    y1 = int(np.clip(y1, y0 + 1, image_h))
    return x0, y0, x1 - x0, y1 - y0


def frame_fraction_distance(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> float:
    return float(np.max(np.abs(np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32))))


def collect_document_frame_consensus(
    src: fitz.Document,
    detect_dpi: int = 72,
    reject_paper_edge_frames: bool = True,
    use_black_white_for_frame_detection: bool = True,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Build a robust document-level median frame rectangle in normalized fractions.
    This helps keep outlier pages aligned with the rest of the PDF.
    """
    fraction_rows = []
    for page_index in range(src.page_count):
        page = src.load_page(page_index)
        img = render_pdf_page_to_bgr(page, dpi=detect_dpi)
        rectified, _ = rectify_page_image(img)
        ink_mask = make_shared_ink_mask(rectified) if use_black_white_for_frame_detection else None
        bbox, confidence = detect_outer_frame_bbox_with_confidence(
            rectified,
            reject_paper_edge_frames=reject_paper_edge_frames,
            use_black_white=use_black_white_for_frame_detection,
            ink_mask=ink_mask,
        )
        if bbox is None:
            continue
        H, W = rectified.shape[:2]
        fracs = bbox_to_fractions(bbox, W, H)
        fraction_rows.append((fracs, confidence))

    if not fraction_rows:
        return None

    frac_arr = np.asarray([row[0] for row in fraction_rows], dtype=np.float32)
    conf_arr = np.asarray([row[1] for row in fraction_rows], dtype=np.float32)

    confident = frac_arr[conf_arr >= max(0.45, float(np.median(conf_arr)) * 0.9)]
    if len(confident) == 0:
        confident = frac_arr

    median = np.median(confident, axis=0)
    dists = np.max(np.abs(confident - median), axis=1)
    kept = confident[dists <= 0.02]
    if len(kept) >= max(2, len(confident) // 2):
        median = np.median(kept, axis=0)

    return tuple(float(v) for v in median)


def normalize_page_mode(

    image: np.ndarray,
    page_size: str,
    dpi: int,
    orientation: str,
    canvas_margin_mm: float,
    page_placement: str,
    page_anchor: str,
) -> np.ndarray:
    rectified, quad = rectify_page_image(image)

    if orientation == "auto":
        if quad is not None:
            landscape = rectified.shape[1] > rectified.shape[0]
        else:
            landscape = image.shape[1] > image.shape[0]
    elif orientation == "landscape":
        landscape = True
    else:
        landscape = False

    canvas_w, canvas_h = page_size_px(page_size, dpi=dpi, landscape=landscape)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    margin_px = mm_to_px(canvas_margin_mm, dpi)
    target_x = margin_px
    target_y = margin_px
    target_w = max(1, canvas_w - 2 * margin_px)
    target_h = max(1, canvas_h - 2 * margin_px)

    anchor_bbox = detect_content_bbox(rectified)
    anchored_page = crop_to_anchor_margins(rectified, anchor_bbox, page_anchor)

    if page_placement == "fill":
        placed = cv2.resize(anchored_page, (target_w, target_h), interpolation=cv2.INTER_AREA)
        canvas[target_y:target_y + target_h, target_x:target_x + target_w] = placed
        return canvas

    place_image_aligned(canvas, anchored_page, target_x, target_y, target_w, target_h, page_anchor)
    return canvas



def normalize_outer_frame_mode(
    image: np.ndarray,
    page_size: str,
    dpi: int,
    orientation: str,
    canvas_margin_mm: float,
    page_anchor: str,
    document_frame_fractions: Optional[Tuple[float, float, float, float]] = None,
    reject_paper_edge_frames: bool = True,
    use_black_white_for_frame_detection: bool = True,
    output_color_mode: str = "color",
    use_shared_bw_corner_lock: bool = True,
) -> np.ndarray:
    rectified, quad = rectify_page_image(image)
    shared_bw = make_shared_black_white_output(rectified) if use_black_white_for_frame_detection else None
    shared_ink_mask = cv2.bitwise_not(shared_bw) if shared_bw is not None else None

    frame_bbox, frame_confidence = detect_outer_frame_bbox_with_confidence(
        rectified,
        reject_paper_edge_frames=reject_paper_edge_frames,
        use_black_white=use_black_white_for_frame_detection,
        ink_mask=shared_ink_mask,
    )

    if orientation == "auto":
        if frame_bbox is not None:
            _, _, fw, fh = frame_bbox
            landscape = fw > fh
        elif quad is not None:
            landscape = rectified.shape[1] > rectified.shape[0]
        else:
            landscape = image.shape[1] > image.shape[0]
    elif orientation == "landscape":
        landscape = True
    else:
        landscape = False

    canvas_w, canvas_h = page_size_px(page_size, dpi=dpi, landscape=landscape)

    src_h, src_w = rectified.shape[:2]
    consensus_bbox = None
    if document_frame_fractions is not None:
        consensus_bbox = fractions_to_bbox(document_frame_fractions, src_w, src_h)

    if consensus_bbox is not None:
        if frame_bbox is None:
            frame_bbox = consensus_bbox
        else:
            page_fracs = bbox_to_fractions(frame_bbox, src_w, src_h)
            diff = frame_fraction_distance(page_fracs, document_frame_fractions)
            if frame_confidence < 0.55 or diff > 0.012:
                frame_bbox = consensus_bbox

    if frame_bbox is None:
        return normalize_page_mode(
            image=image,
            page_size=page_size,
            dpi=dpi,
            orientation=orientation,
            canvas_margin_mm=canvas_margin_mm,
            page_placement="fill",
            page_anchor=page_anchor,
        )

    x, y, bw, bh = frame_bbox

    margin_px = mm_to_px(canvas_margin_mm, dpi)
    target_x = margin_px
    target_y = margin_px
    target_w = max(1, canvas_w - 2 * margin_px)
    target_h = max(1, canvas_h - 2 * margin_px)

    sx = target_w / bw
    sy = target_h / bh

    use_binary_source = (
        output_color_mode.lower() == "black_white"
        and use_black_white_for_frame_detection
        and use_shared_bw_corner_lock
        and shared_bw is not None
    )
    source_img = shared_bw if use_binary_source else rectified

    new_w = max(1, int(round(src_w * sx)))
    new_h = max(1, int(round(src_h * sy)))
    if use_binary_source:
        interpolation = cv2.INTER_NEAREST
    else:
        interpolation = cv2.INTER_CUBIC if sx > 1.0 or sy > 1.0 else cv2.INTER_AREA
    scaled = cv2.resize(source_img, (new_w, new_h), interpolation=interpolation)

    scaled_right = int(round((x + bw) * sx))
    scaled_bottom = int(round((y + bh) * sy))
    target_br_x = target_x + target_w
    target_br_y = target_y + target_h
    paste_x = target_br_x - scaled_right
    paste_y = target_br_y - scaled_bottom

    if use_binary_source:
        canvas = np.full((canvas_h, canvas_w), 255, dtype=np.uint8)
    else:
        canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    paste_image_with_offset(canvas, scaled, paste_x, paste_y)
    return canvas


def normalize_content_mode(

    image: np.ndarray,
    page_size: str,
    dpi: int,
    margin_mm: float,
    orientation: str,
    template_fractions: Optional[Tuple[float, float, float, float]] = None,
) -> np.ndarray:
    rectified, _ = rectify_page_image(image)
    x, y, w, h = detect_content_bbox(rectified)
    content = rectified[y:y + h, x:x + w]

    if orientation == "auto":
        landscape = w > h
    elif orientation == "landscape":
        landscape = True
    else:
        landscape = False

    canvas_w, canvas_h = page_size_px(page_size, dpi=dpi, landscape=landscape)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    if template_fractions is not None:
        fx, fy, fw, fh = template_fractions
        target_x = int(round(fx * canvas_w))
        target_y = int(round(fy * canvas_h))
        target_w = max(1, int(round(fw * canvas_w)))
        target_h = max(1, int(round(fh * canvas_h)))
    else:
        margin_px = mm_to_px(margin_mm, dpi=dpi)
        target_x = margin_px
        target_y = margin_px
        target_w = max(1, canvas_w - (2 * margin_px))
        target_h = max(1, canvas_h - (2 * margin_px))

    place_image_aligned(canvas, content, target_x, target_y, target_w, target_h, anchor="C")
    return canvas


def normalize_scanned_page(
    image: np.ndarray,
    page_size: str,
    dpi: int,
    margin_mm: float,
    orientation: str,
    mode: str,
    canvas_margin_mm: float,
    template_fractions: Optional[Tuple[float, float, float, float]] = None,
    page_placement: str = "fill",
    page_anchor: str = "BR",
    document_frame_fractions: Optional[Tuple[float, float, float, float]] = None,
    reject_paper_edge_frames: bool = True,
    output_color_mode: str = "color",
    use_black_white_for_frame_detection: bool = True,
    use_shared_bw_corner_lock: bool = True,
) -> np.ndarray:
    if mode == "page":
        return normalize_page_mode(
            image=image,
            page_size=page_size,
            dpi=dpi,
            orientation=orientation,
            canvas_margin_mm=canvas_margin_mm,
            page_placement=page_placement,
            page_anchor=page_anchor,
        )

    if mode == "outer_frame":
        return normalize_outer_frame_mode(
            image=image,
            page_size=page_size,
            dpi=dpi,
            orientation=orientation,
            canvas_margin_mm=canvas_margin_mm,
            page_anchor=page_anchor,
            document_frame_fractions=document_frame_fractions,
            reject_paper_edge_frames=reject_paper_edge_frames,
            use_black_white_for_frame_detection=use_black_white_for_frame_detection,
            output_color_mode=output_color_mode,
            use_shared_bw_corner_lock=use_shared_bw_corner_lock,
        )

    return normalize_content_mode(
        image=image,
        page_size=page_size,
        dpi=dpi,
        margin_mm=margin_mm,
        orientation=orientation,
        template_fractions=template_fractions,
    )


def apply_output_color_mode(image: np.ndarray, output_color_mode: str) -> np.ndarray:
    mode = output_color_mode.lower()
    if mode == "color":
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    if mode == "grayscale":
        return gray

    if mode == "black_white":
        if image.ndim == 2:
            unique = np.unique(image)
            if set(unique.tolist()).issubset({0, 255}):
                return image
            return make_shared_black_white_output(image)
        return make_shared_black_white_output(image)

    raise ValueError(f"Unsupported output color mode: {output_color_mode}")


def image_to_pdf_bytes(image: np.ndarray, output_color_mode: str) -> bytes:
    prepared = apply_output_color_mode(image, output_color_mode)
    ok, encoded = cv2.imencode(".png", prepared)
    if not ok:
        raise RuntimeError("Failed to encode page image to PNG.")
    return encoded.tobytes()


def add_image_page_to_pdf(out_doc: fitz.Document, img: np.ndarray, dpi: int, output_color_mode: str) -> None:
    h, w = img.shape[:2]
    page_w_pt = w * 72.0 / dpi
    page_h_pt = h * 72.0 / dpi
    page = out_doc.new_page(width=page_w_pt, height=page_h_pt)
    page.insert_image(page.rect, stream=image_to_pdf_bytes(img, output_color_mode))


def process_pdf(
    input_pdf: Path,
    output_pdf: Path,
    page_size: str,
    dpi: int,
    margin_mm: float,
    orientation: str,
    mode: str,
    canvas_margin_mm: float,
    template_fractions: Optional[Tuple[float, float, float, float]],
    page_placement: str = "fill",
    page_anchor: str = "BR",
    use_document_frame_consensus: bool = True,
    output_color_mode: str = "color",
    reject_paper_edge_frames: bool = True,
    use_black_white_for_frame_detection: bool = True,
    use_shared_bw_corner_lock: bool = True,
) -> None:
    src = fitz.open(input_pdf)
    out_doc = fitz.open()
    try:
        document_frame_fractions = None
        if mode == "outer_frame" and use_document_frame_consensus:
            document_frame_fractions = collect_document_frame_consensus(
                src,
                detect_dpi=min(96, dpi),
                reject_paper_edge_frames=reject_paper_edge_frames,
                use_black_white_for_frame_detection=use_black_white_for_frame_detection,
            )
        for page_index in range(src.page_count):
            page = src.load_page(page_index)
            img = render_pdf_page_to_bgr(page, dpi=dpi)
            normalized = normalize_scanned_page(
                image=img,
                page_size=page_size,
                dpi=dpi,
                margin_mm=margin_mm,
                orientation=orientation,
                mode=mode,
                canvas_margin_mm=canvas_margin_mm,
                template_fractions=template_fractions,
                page_placement=page_placement,
                page_anchor=page_anchor,
                document_frame_fractions=document_frame_fractions,
                reject_paper_edge_frames=reject_paper_edge_frames,
                output_color_mode=output_color_mode,
                use_black_white_for_frame_detection=use_black_white_for_frame_detection,
                use_shared_bw_corner_lock=use_shared_bw_corner_lock,
            )
            add_image_page_to_pdf(out_doc=out_doc, img=normalized, dpi=dpi, output_color_mode=output_color_mode)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_doc.save(output_pdf, deflate=True, garbage=4)
    finally:
        src.close()
        out_doc.close()


def build_arg_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description="Escanor - normalize scanned PDFs by rectifying the whole page, the content area, or the printed outer frame onto a fixed ISO page."
    )
    parser.add_argument("--input", required=True, help="Input PDF file or folder.")
    parser.add_argument("--output", required=True, help="Output folder, or output PDF path when input is a single PDF.")
    parser.add_argument("--page-size", required=True, choices=sorted(ISO_SIZES_MM.keys()), help="Target page size.")
    parser.add_argument("--dpi", type=int, default=200, help="Render/output DPI. Higher = better quality, slower and larger files.")
    parser.add_argument(
        "--mode",
        choices=["page", "content", "outer_frame"],
        default="page",
        help=(
            "page = normalize the full sheet. "
            "content = crop actual content and re-place it. "
            "outer_frame = detect and normalize the printed outer frame rectangle."
        ),
    )
    parser.add_argument("--margin-mm", type=float, default=10.0, help="Used in content mode when no template is used.")
    parser.add_argument(
        "--canvas-margin-mm",
        type=float,
        default=0.0,
        help="Used in page/outer_frame modes. Adds a uniform white outer gutter around the normalized page.",
    )
    parser.add_argument(
        "--page-placement",
        choices=["fill", "balanced"],
        default="fill",
        help="page mode only. fill = anchor-aware full-box fill. balanced = anchor-aware fit inside the target box.",
    )
    parser.add_argument(
        "--page-anchor",
        choices=ANCHOR_CHOICES,
        default="BR",
        help="page mode fallback anchor. In outer_frame mode this is only used if frame detection fails.",
    )
    parser.add_argument(
        "--disable-document-frame-consensus",
        action="store_true",
        help="outer_frame mode only. Disable the document-level median frame consensus used to stabilize outlier pages.",
    )
    parser.add_argument(
        "--allow-paper-edge-frames",
        action="store_true",
        help="outer_frame mode only. Allow detections that hug the paper edge even when they do not look like a true inset printed frame.",
    )
    parser.add_argument(
        "--disable-black-white-frame-detection",
        action="store_true",
        help="outer_frame mode only. Do not use a black-and-white mask to find faint printed frame lines.",
    )
    parser.add_argument(
        "--disable-shared-bw-corner-lock",
        action="store_true",
        help="outer_frame + black_white only. Do not reuse the same B/W mask for final BR corner locking and export.",
    )
    parser.add_argument(
        "--output-color-mode",
        choices=["color", "grayscale", "black_white"],
        default="color",
        help="Output color mode. black_white produces a binary black/white PDF for smaller files and faster output.",
    )
    parser.add_argument(
        "--orientation",
        choices=["auto", "portrait", "landscape"],
        default="auto",
        help="Output page orientation.",
    )
    parser.add_argument(
        "--template",
        help="Optional template PDF or image. Mainly useful in content mode to copy target placement.",
    )
    parser.add_argument("--recursive", action="store_true", help="Recursively scan subfolders for PDFs.")
    return parser


def resolve_output_path(input_pdf: Path, output_arg: Path, single_input: bool) -> Path:
    if single_input and output_arg.suffix.lower() == ".pdf":
        return output_arg
    output_arg.mkdir(parents=True, exist_ok=True)
    return output_arg / f"{input_pdf.stem}_normalized.pdf"


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    output_arg = Path(args.output)

    pdfs = list_input_pdfs(input_path, recursive=args.recursive)
    if not pdfs:
        raise SystemExit("No PDF files found.")

    template_fractions = None
    if args.template and args.mode == "content":
        template_path = Path(args.template)
        template_img = load_template_image(template_path, dpi=args.dpi)
        template_fractions = compute_template_content_fractions(template_img)
        print(f"Template placement fractions loaded: {template_fractions}")
    elif args.template and args.mode in {"page", "outer_frame"}:
        print("Template supplied, but this mode does not need template placement. Proceeding without template placement.")

    single_input = input_path.is_file()

    for idx, pdf_path in enumerate(pdfs, start=1):
        out_pdf = resolve_output_path(pdf_path, output_arg, single_input=single_input)
        print(f"[{idx}/{len(pdfs)}] Processing: {pdf_path.name}")
        process_pdf(
            input_pdf=pdf_path,
            output_pdf=out_pdf,
            page_size=args.page_size,
            dpi=args.dpi,
            margin_mm=args.margin_mm,
            orientation=args.orientation,
            mode=args.mode,
            canvas_margin_mm=args.canvas_margin_mm,
            template_fractions=template_fractions,
            page_placement=args.page_placement,
            page_anchor=args.page_anchor,
            use_document_frame_consensus=not args.disable_document_frame_consensus,
            output_color_mode=args.output_color_mode,
            reject_paper_edge_frames=not args.allow_paper_edge_frames,
            use_black_white_for_frame_detection=not args.disable_black_white_frame_detection,
            use_shared_bw_corner_lock=not args.disable_shared_bw_corner_lock,
        )
        print(f"    Saved: {out_pdf}")

    print("Done.")


if __name__ == "__main__":
    main()
