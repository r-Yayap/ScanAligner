import numpy as np
import cv2

from app.infrastructure.imaging.page_analyzer import AnalyzerConfig, PageAnalyzer


def test_page_analyzer_detects_content_rect() -> None:
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (60, 50), (250, 160), (0, 0, 0), -1)
    analyzer = PageAnalyzer()
    result = analyzer.analyze(img, AnalyzerConfig(content_threshold=200, edge_dark_threshold=30))
    assert result.content_rect.w > 150
    assert result.content_rect.h > 80
