from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QPlainTextEdit, QTextEdit, QTreeWidget, QWidget


def widget_bounds(widget: QWidget, root: QWidget) -> QRect:
    return QRect(widget.mapTo(root, QPoint(0, 0)), widget.size())


def assert_contained(parent: QWidget, child: QWidget, root: QWidget) -> None:
    parent_rect = widget_bounds(parent, root).adjusted(-1, -1, 1, 1)
    child_rect = widget_bounds(child, root)
    assert child_rect.width() > 0
    assert child_rect.height() > 0
    assert parent_rect.contains(child_rect), f"{_widget_name(child)} escaped {_widget_name(parent)}"


def assert_no_visual_overlap(widgets: list[QWidget], root: QWidget) -> None:
    rects = [(widget_bounds(widget, root), widget) for widget in widgets if widget.isVisible()]
    for index, (left_rect, left_widget) in enumerate(rects):
        assert left_rect.width() > 0
        assert left_rect.height() > 0
        for right_rect, right_widget in rects[index + 1 :]:
            assert not left_rect.intersects(right_rect), (
                f"{_widget_name(left_widget)} overlaps {_widget_name(right_widget)}"
            )


def visible_label_text(root: QWidget) -> str:
    return "\n".join(
        label.text()
        for label in root.findChildren(QLabel)
        if label.isVisibleTo(root) and label.text()
    )


def assert_no_visible_competitor_name(root: QWidget) -> None:
    texts = [visible_label_text(root)]
    for widget in root.findChildren(QWidget):
        if not widget.isVisibleTo(root):
            continue
        if widget.toolTip():
            texts.append(widget.toolTip())
        if isinstance(widget, QAbstractButton):
            texts.append(widget.text())
        elif isinstance(widget, QComboBox):
            texts.extend(widget.itemText(index) for index in range(widget.count()))
        elif isinstance(widget, QPlainTextEdit):
            texts.append(widget.toPlainText())
        elif isinstance(widget, QTextEdit):
            texts.append(widget.toPlainText())
        elif isinstance(widget, QTreeWidget):
            for index in range(widget.topLevelItemCount()):
                item = widget.topLevelItem(index)
                texts.append(item.text(0))
                texts.append(item.toolTip(0))
    text = "\n".join(texts)
    for forbidden in ("EddyPro", "EDDYPRO", "eddypro", "行业参考", "raw-to-final"):
        assert forbidden not in text


def _widget_name(widget: QWidget) -> str:
    for key in ("deckRole", "gateKey", "evidenceKey", "cardRole"):
        value = widget.property(key)
        if value:
            return str(value)
    return widget.objectName() or widget.__class__.__name__
