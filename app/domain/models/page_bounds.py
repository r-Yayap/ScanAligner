from dataclasses import dataclass


@dataclass(slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class PageAnalysis:
    content_rect: Rect
    crop_rect: Rect
    skew_angle: float
