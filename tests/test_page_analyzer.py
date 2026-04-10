import numpy as np
import cv2

from app.domain.models.page_bounds import Rect
from app.infrastructure.imaging.page_analyzer import AnalyzerConfig, PageAnalyzer


def test_page_analyzer_detects_content_rect() -> None:
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (60, 50), (250, 160), (0, 0, 0), -1)
    analyzer = PageAnalyzer()
    result = analyzer.analyze(img, AnalyzerConfig(content_threshold=200, edge_dark_threshold=30))
    assert result.content_rect.w > 150
    assert result.content_rect.h > 80


def test_page_analyzer_respects_manual_title_block_override() -> None:
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    analyzer = PageAnalyzer()
    manual_rect = Rect(20, 30, 80, 40)
    result = analyzer.analyze(
        img,
        AnalyzerConfig(content_threshold=200, edge_dark_threshold=30, detect_title_block=False, manual_title_block_rect=manual_rect),
    )
    assert result.title_block_rect == manual_rect
