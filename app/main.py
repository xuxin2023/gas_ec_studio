from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import apply_app_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Gas EC Studio")
    apply_app_theme(app)
    controller = StudioController()
    window = StudioMainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
