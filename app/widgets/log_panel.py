from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import CardFrame, TOKENS, chip
from app.ui_refresh import set_text_if_changed
from app.ui_text import ui_safe_text


class LogPanel(CardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(muted=True, role="console", parent=parent)
        self._expanded = False
        self._last_lines: tuple[str, ...] = ()
        self.setProperty("logPanelCompactDock", True)
        self._collapsed_height = 44
        self._expanded_min_height = 180
        self._expanded_max_height = 260
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(self._collapsed_height)
        self.setMaximumHeight(self._collapsed_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, 2, TOKENS.spacing_md, 2)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(TOKENS.spacing_sm)
        title = QLabel("运行日志")
        title.setObjectName("sectionTitle")
        title.setMaximumHeight(20)
        header.addWidget(title)

        self.log_count_chip = chip("0 条", "accent")
        self.log_count_chip.setMaximumHeight(20)
        header.addWidget(self.log_count_chip)

        self.latest_line = QLabel("暂无日志。")
        self.latest_line.setObjectName("subtitle")
        self.latest_line.setProperty("logLatestLine", True)
        self.latest_line.setWordWrap(False)
        self.latest_line.setMinimumWidth(0)
        self.latest_line.setMaximumHeight(20)
        self.latest_line.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        header.addWidget(self.latest_line, 1)

        self.toggle_button = QToolButton()
        self.toggle_button.setText("展开")
        self.toggle_button.setProperty("logPanelAction", True)
        self.toggle_button.setMaximumHeight(24)
        self.toggle_button.clicked.connect(self.toggle)
        header.addWidget(self.toggle_button)

        self.clear_button = QPushButton("清空日志")
        self.clear_button.setProperty("logPanelAction", True)
        self.clear_button.setMaximumHeight(24)
        self.clear_button.clicked.connect(self.clear)
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        self.tip = QLabel("采用面向人的中文提示，协议细节保留给工程师排障使用。")
        self.tip.setObjectName("subtitle")
        layout.addWidget(self.tip)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setMaximumBlockCount(1000)
        layout.addWidget(self.editor, 1)
        self.set_expanded(False)

    def set_lines(self, lines: list[str]) -> None:
        safe_lines = tuple(ui_safe_text(line) for line in lines)
        if safe_lines == self._last_lines:
            return
        self._last_lines = safe_lines
        self.editor.setPlainText("\n".join(safe_lines))
        set_text_if_changed(self.log_count_chip, f"{len(safe_lines)} 条")
        set_text_if_changed(self.latest_line, safe_lines[0] if safe_lines else "暂无日志。")
        self.latest_line.setToolTip(self.latest_line.text())
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def clear(self) -> None:
        self._last_lines = ()
        self.editor.clear()
        set_text_if_changed(self.log_count_chip, "0 条")
        set_text_if_changed(self.latest_line, "暂无日志。")
        self.latest_line.setToolTip(self.latest_line.text())

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.editor.setVisible(self._expanded)
        self.tip.setVisible(self._expanded)
        self.latest_line.setVisible(not self._expanded)
        self.toggle_button.setText("折叠" if self._expanded else "展开")
        self.setMinimumHeight(self._expanded_min_height if self._expanded else self._collapsed_height)
        self.setMaximumHeight(self._expanded_max_height if self._expanded else self._collapsed_height)
