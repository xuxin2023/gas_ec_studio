from __future__ import annotations

from PySide6.QtCore import Qt
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


class LogPanel(CardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(muted=True, role="console", parent=parent)
        self._expanded = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(84)
        self.setMaximumHeight(84)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        title = QLabel("底部日志面板")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self.log_count_chip = chip("0 条", "accent")
        header.addWidget(self.log_count_chip)
        header.addStretch(1)

        self.toggle_button = QToolButton()
        self.toggle_button.setText("展开")
        self.toggle_button.clicked.connect(self.toggle)
        header.addWidget(self.toggle_button)

        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.clear)
        header.addWidget(clear_button)
        layout.addLayout(header)

        self.tip = QLabel("采用面向人的中文提示，协议细节保留给工程师排障使用。")
        self.tip.setObjectName("subtitle")
        layout.addWidget(self.tip)

        self.latest_line = QLabel("暂无日志。")
        self.latest_line.setObjectName("subtitle")
        self.latest_line.setWordWrap(True)
        layout.addWidget(self.latest_line)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setMaximumBlockCount(1000)
        layout.addWidget(self.editor, 1)
        self.set_expanded(False)

    def set_lines(self, lines: list[str]) -> None:
        self.editor.setPlainText("\n".join(lines))
        self.log_count_chip.setText(f"{len(lines)} 条")
        self.latest_line.setText(lines[0] if lines else "暂无日志。")
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def clear(self) -> None:
        self.editor.clear()
        self.log_count_chip.setText("0 条")
        self.latest_line.setText("暂无日志。")

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.editor.setVisible(self._expanded)
        self.tip.setVisible(self._expanded)
        self.latest_line.setVisible(not self._expanded)
        self.toggle_button.setText("折叠" if self._expanded else "展开")
        self.setMinimumHeight(180 if self._expanded else 84)
        self.setMaximumHeight(260 if self._expanded else 84)
