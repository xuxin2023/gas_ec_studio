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

from app.theme import CardFrame, TOKENS


class LogPanel(CardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(muted=True, role="console", parent=parent)
        self._expanded = True
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        title = QLabel("底部日志面板")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.toggle_button = QToolButton()
        self.toggle_button.setText("折叠")
        self.toggle_button.clicked.connect(self.toggle)
        header.addWidget(self.toggle_button)

        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.clear)
        header.addWidget(clear_button)
        layout.addLayout(header)

        tip = QLabel("采用面向人的中文提示，协议细节保留给工程师排障使用。")
        tip.setObjectName("subtitle")
        layout.addWidget(tip)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setMaximumBlockCount(1000)
        layout.addWidget(self.editor, 1)

    def set_lines(self, lines: list[str]) -> None:
        self.editor.setPlainText("\n".join(lines))
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def clear(self) -> None:
        self.editor.clear()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self.editor.setVisible(self._expanded)
        self.toggle_button.setText("折叠" if self._expanded else "展开")
        self.setMinimumHeight(180 if self._expanded else 74)
        self.setMaximumHeight(260 if self._expanded else 74)
