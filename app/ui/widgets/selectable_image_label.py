from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel


class SelectableImageLabel(QLabel):
    selection_changed = Signal(tuple)

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(450, 600)
        self._source_pixmap: QPixmap | None = None
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._selection_image_rect: QRect | None = None
        self._selection_enabled = False

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def set_display_pixmap(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        self._drag_start = None
        self._drag_current = None
        super().setPixmap(self._scaled_pixmap())
        self.update()

    def clear_selection(self) -> None:
        self._selection_image_rect = None
        self._drag_start = None
        self._drag_current = None
        self.update()

    def selected_image_rect(self) -> tuple[int, int, int, int] | None:
        if self._selection_image_rect is None:
            return None
        r = self._selection_image_rect
        return r.x(), r.y(), r.width(), r.height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._source_pixmap is not None:
            super().setPixmap(self._scaled_pixmap())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._selection_enabled or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        image_pos = self._widget_to_image(event.position().toPoint())
        if image_pos is None:
            return
        self._drag_start = image_pos
        self._drag_current = image_pos
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._selection_enabled or self._drag_start is None:
            return super().mouseMoveEvent(event)
        image_pos = self._widget_to_image(event.position().toPoint())
        if image_pos is None:
            return
        self._drag_current = image_pos
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._selection_enabled or self._drag_start is None:
            return super().mouseReleaseEvent(event)
        image_pos = self._widget_to_image(event.position().toPoint())
        if image_pos is None:
            return
        self._drag_current = image_pos
        rect = QRect(self._drag_start, self._drag_current).normalized()
        if rect.width() >= 8 and rect.height() >= 8:
            self._selection_image_rect = rect
            self.selection_changed.emit((rect.x(), rect.y(), rect.width(), rect.height()))
        self._drag_start = None
        self._drag_current = None
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(Qt.green, 2))

        if self._selection_image_rect is not None:
            widget_rect = self._image_to_widget_rect(self._selection_image_rect)
            if widget_rect is not None:
                painter.drawRect(widget_rect)

        if self._drag_start is not None and self._drag_current is not None:
            drag_rect = QRect(self._drag_start, self._drag_current).normalized()
            widget_rect = self._image_to_widget_rect(drag_rect)
            if widget_rect is not None:
                painter.setPen(QPen(Qt.yellow, 2, Qt.DashLine))
                painter.drawRect(widget_rect)

    def _scaled_pixmap(self) -> QPixmap:
        if self._source_pixmap is None:
            return QPixmap()
        return self._source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _pixmap_geometry(self) -> tuple[int, int, int, int] | None:
        if self._source_pixmap is None:
            return None
        scaled = self._scaled_pixmap()
        x_off = (self.width() - scaled.width()) // 2
        y_off = (self.height() - scaled.height()) // 2
        return x_off, y_off, scaled.width(), scaled.height()

    def _widget_to_image(self, p: QPoint) -> QPoint | None:
        geom = self._pixmap_geometry()
        if geom is None or self._source_pixmap is None:
            return None
        x_off, y_off, draw_w, draw_h = geom
        if p.x() < x_off or p.x() >= x_off + draw_w or p.y() < y_off or p.y() >= y_off + draw_h:
            return None
        rel_x = (p.x() - x_off) / max(draw_w, 1)
        rel_y = (p.y() - y_off) / max(draw_h, 1)
        img_x = int(rel_x * self._source_pixmap.width())
        img_y = int(rel_y * self._source_pixmap.height())
        return QPoint(img_x, img_y)

    def _image_to_widget_rect(self, rect: QRect) -> QRect | None:
        geom = self._pixmap_geometry()
        if geom is None or self._source_pixmap is None:
            return None
        x_off, y_off, draw_w, draw_h = geom
        x = x_off + int(rect.x() / max(self._source_pixmap.width(), 1) * draw_w)
        y = y_off + int(rect.y() / max(self._source_pixmap.height(), 1) * draw_h)
        w = int(rect.width() / max(self._source_pixmap.width(), 1) * draw_w)
        h = int(rect.height() / max(self._source_pixmap.height(), 1) * draw_h)
        return QRect(x, y, max(1, w), max(1, h))
