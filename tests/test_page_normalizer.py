import numpy as np

from app.domain.models.page_bounds import PageAnalysis, Rect
from app.infrastructure.imaging.page_normalizer import NormalizeConfig, PageNormalizer


def _analysis(w: int, h: int) -> PageAnalysis:
    return PageAnalysis(
        content_rect=Rect(0, 0, w, h),
        crop_rect=Rect(0, 0, w, h),
        skew_angle=0.0,
    )


def _analysis_with_title_block(page_w: int, page_h: int, tb_x: int, tb_y: int, tb_w: int, tb_h: int) -> PageAnalysis:
    return PageAnalysis(
        content_rect=Rect(0, 0, page_w, page_h),
        crop_rect=Rect(0, 0, page_w, page_h),
        skew_angle=0.0,
        title_block_rect=Rect(tb_x, tb_y, tb_w, tb_h),
    )


def test_bottom_right_anchor_places_content_against_margins() -> None:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    normalizer = PageNormalizer()
    result = normalizer.normalize(
        image,
        _analysis(20, 20),
        NormalizeConfig(deskew=False, normalize_margins=True, margin_ratio=0.1, anchor="bottom_right"),
        (100, 100),
    )
    ys, xs = np.where(np.any(result < 250, axis=2))
    assert xs.max() == 89
    assert ys.max() == 89


def test_reference_content_size_keeps_smaller_pages_at_same_scale() -> None:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    normalizer = PageNormalizer()
    result = normalizer.normalize(
        image,
        _analysis(20, 20),
        NormalizeConfig(
            deskew=False,
            normalize_margins=True,
            margin_ratio=0.1,
            anchor="center",
            reference_content_size=(40, 40),
        ),
        (100, 100),
    )
    ys, xs = np.where(np.any(result < 250, axis=2))
    assert xs.max() - xs.min() + 1 == 40
    assert ys.max() - ys.min() + 1 == 40


def test_title_block_alignment_locks_bottom_right_position() -> None:
    image = np.full((50, 80, 3), 255, dtype=np.uint8)
    image[35:45, 60:76] = 0
    normalizer = PageNormalizer()
    result = normalizer.normalize(
        image,
        _analysis_with_title_block(80, 50, 60, 35, 16, 10),
        NormalizeConfig(
            deskew=False,
            normalize_margins=True,
            margin_ratio=0.1,
            anchor="bottom_right",
            align_to_title_block=True,
        ),
        (200, 120),
    )
    ys, xs = np.where(np.any(result < 40, axis=2))
    assert xs.max() == 179
    assert ys.max() == 107
