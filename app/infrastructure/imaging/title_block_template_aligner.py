from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


class TitleBlockAlignmentError(RuntimeError):
    """Raised when title block detection/alignment fails."""


def preprocess_for_features(image_bgr: np.ndarray) -> np.ndarray:
    """Apply light scan-friendly preprocessing before feature extraction."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return cv2.GaussianBlur(gray, (3, 3), 0)


def create_detector(prefer_sift: bool = True, nfeatures: int = 4000):
    """Create a feature detector/matcher pair.

    SIFT is preferred when available due to better stability on noisy scans.
    """
    if prefer_sift and hasattr(cv2, "SIFT_create"):
        detector = cv2.SIFT_create(nfeatures=nfeatures)
        matcher = cv2.FlannBasedMatcher(
            dict(algorithm=1, trees=5),  # KD-Tree for float descriptors
            dict(checks=50),
        )
        return detector, matcher, "SIFT"

    detector = cv2.ORB_create(nfeatures=nfeatures, fastThreshold=10)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    return detector, matcher, "ORB"


def knn_ratio_match(
    descriptors_query: np.ndarray,
    descriptors_train: np.ndarray,
    matcher,
    ratio: float = 0.75,
):
    """Apply Lowe ratio filtering to KNN matches."""
    knn_matches = matcher.knnMatch(descriptors_query, descriptors_train, k=2)
    good_matches = []
    for pair in knn_matches:
        if len(pair) < 2:
            continue
        first, second = pair
        if first.distance < ratio * second.distance:
            good_matches.append(first)
    return good_matches


def draw_polygon(image_bgr: np.ndarray, polygon_points: np.ndarray) -> np.ndarray:
    """Draw detected title block polygon on top of the scanned page."""
    output = image_bgr.copy()
    pts_int = np.int32(polygon_points).reshape(-1, 1, 2)
    cv2.polylines(output, [pts_int], isClosed=True, color=(0, 255, 0), thickness=3)
    return output


def align_scan_from_title_block(
    template_path: str | Path,
    scan_path: str | Path,
    output_prefix: str | Path,
    prefer_sift: bool = True,
    ratio: float = 0.75,
    min_good_matches: int = 25,
    ransac_reprojection_threshold: float = 4.0,
) -> dict[str, int | str]:
    """Detect title block from template and realign scanned page.

    Returns basic run stats for logging/automation.
    """
    template_bgr = cv2.imread(str(template_path))
    if template_bgr is None:
        raise FileNotFoundError(f"Could not read template image: {template_path}")

    scan_bgr = cv2.imread(str(scan_path))
    if scan_bgr is None:
        raise FileNotFoundError(f"Could not read scan image: {scan_path}")

    template_gray = preprocess_for_features(template_bgr)
    scan_gray = preprocess_for_features(scan_bgr)

    detector, matcher, detector_name = create_detector(prefer_sift=prefer_sift)
    keypoints_template, descriptors_template = detector.detectAndCompute(template_gray, None)
    keypoints_scan, descriptors_scan = detector.detectAndCompute(scan_gray, None)

    if descriptors_template is None or descriptors_scan is None:
        raise TitleBlockAlignmentError("No descriptors found in template or scan image.")

    good_matches = knn_ratio_match(descriptors_template, descriptors_scan, matcher, ratio=ratio)

    if len(good_matches) < min_good_matches:
        raise TitleBlockAlignmentError(
            f"Not enough good matches ({len(good_matches)} < {min_good_matches})."
        )

    source_points = np.float32([keypoints_template[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    destination_points = np.float32([keypoints_scan[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    homography_template_to_scan, inlier_mask = cv2.findHomography(
        source_points,
        destination_points,
        cv2.RANSAC,
        ransac_reprojection_threshold,
    )

    if homography_template_to_scan is None:
        raise TitleBlockAlignmentError("Homography estimation failed.")

    inlier_count = int(inlier_mask.sum()) if inlier_mask is not None else 0
    if inlier_count < max(12, int(0.25 * len(good_matches))):
        raise TitleBlockAlignmentError(
            f"Homography is unreliable: only {inlier_count} inliers from {len(good_matches)} matches."
        )

    template_height, template_width = template_gray.shape[:2]
    template_corners = np.float32(
        [[0, 0], [template_width - 1, 0], [template_width - 1, template_height - 1], [0, template_height - 1]]
    ).reshape(-1, 1, 2)

    title_block_polygon_on_scan = cv2.perspectiveTransform(template_corners, homography_template_to_scan)
    detected_overlay = draw_polygon(scan_bgr, title_block_polygon_on_scan)

    homography_scan_to_template = np.linalg.inv(homography_template_to_scan)
    scan_height, scan_width = scan_gray.shape[:2]
    aligned_scan = cv2.warpPerspective(
        scan_bgr,
        homography_scan_to_template,
        (scan_width, scan_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    matches_preview = cv2.drawMatches(
        template_bgr,
        keypoints_template,
        scan_bgr,
        keypoints_scan,
        good_matches[:100],
        None,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )

    output_prefix_path = Path(output_prefix)
    output_prefix_path.parent.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(f"{output_prefix_path}_detected_titleblock.png", detected_overlay)
    cv2.imwrite(f"{output_prefix_path}_aligned_scan.png", aligned_scan)
    cv2.imwrite(f"{output_prefix_path}_matches.png", matches_preview)

    return {
        "detector": detector_name,
        "template_keypoints": len(keypoints_template),
        "scan_keypoints": len(keypoints_scan),
        "good_matches": len(good_matches),
        "inliers": inlier_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect title block from a template image and realign a scanned page."
    )
    parser.add_argument("--template", required=True, help="Path to title block template image")
    parser.add_argument("--scan", required=True, help="Path to scanned page image")
    parser.add_argument("--out-prefix", default="result/out", help="Output file prefix")
    parser.add_argument("--use-orb", action="store_true", help="Force ORB instead of SIFT")
    parser.add_argument("--ratio", type=float, default=0.75, help="Lowe ratio test threshold")
    parser.add_argument("--min-good", type=int, default=25, help="Minimum good matches required")
    parser.add_argument(
        "--ransac",
        type=float,
        default=4.0,
        help="RANSAC reprojection threshold",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    stats = align_scan_from_title_block(
        template_path=args.template,
        scan_path=args.scan,
        output_prefix=args.out_prefix,
        prefer_sift=not args.use_orb,
        ratio=args.ratio,
        min_good_matches=args.min_good,
        ransac_reprojection_threshold=args.ransac,
    )

    print("[OK] Alignment artifacts saved:")
    print(f"  - {args.out_prefix}_detected_titleblock.png")
    print(f"  - {args.out_prefix}_aligned_scan.png")
    print(f"  - {args.out_prefix}_matches.png")
    print("[INFO] Stats:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")


if __name__ == "__main__":
    main()
