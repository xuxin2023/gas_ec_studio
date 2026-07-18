from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QTimer, Slot
from PySide6.QtWidgets import QWidget


class CoalescedWidgetRefresh(QObject):
    """Coalesce signal storms and paint a visible widget once per interval."""

    def __init__(
        self,
        owner: QWidget,
        callback: Callable[[], None],
        *,
        interval_ms: int = 250,
        visible_only: bool = True,
        stabilize_updates: bool = True,
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.callback = callback
        self.visible_only = visible_only
        self.stabilize_updates = stabilize_updates
        self.flush_count = 0
        self._pending = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(interval_ms)))
        self._timer.timeout.connect(self.flush)
        owner.installEventFilter(self)

    def request(self, *_args: object) -> None:
        self._pending = True
        if self.visible_only and not self.owner.isVisible():
            return
        if not self._timer.isActive():
            self._timer.start()

    def request_now(self, *_args: object) -> None:
        self._pending = True
        if self.visible_only and not self.owner.isVisible():
            return
        self._timer.stop()
        self.flush()

    @Slot()
    def flush(self) -> None:
        if not self._pending:
            return
        if self.visible_only and not self.owner.isVisible():
            return

        self._pending = False
        updates_were_enabled = self.owner.updatesEnabled()
        if self.stabilize_updates and updates_were_enabled:
            self.owner.setUpdatesEnabled(False)
        try:
            self.callback()
            self.flush_count += 1
        finally:
            if self.stabilize_updates and updates_were_enabled:
                self.owner.setUpdatesEnabled(True)
                self.owner.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.owner and event.type() == QEvent.Type.Show and self._pending:
            self._timer.start(0)
        return False


def set_text_if_changed(widget, text: str) -> bool:
    if widget.text() == text:
        return False
    widget.setText(text)
    return True


def set_dynamic_property(widget: QWidget, name: str, value: object) -> bool:
    if widget.property(name) == value:
        return False
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
    return True
