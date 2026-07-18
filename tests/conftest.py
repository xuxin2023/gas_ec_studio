from __future__ import annotations

import os
from typing import Any

import pytest


_QT_APP: Any | None = None


def pytest_configure() -> None:
    """Keep one offscreen QApplication alive for the whole test process.

    Several UI tests create widgets without using pytest-qt. Holding a process
    level QApplication avoids Windows/PySide teardown crashes after all tests
    have already completed.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    global _QT_APP
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    _QT_APP = QApplication.instance() or QApplication([])
    _QT_APP.setQuitOnLastWindowClosed(False)


def pytest_sessionfinish() -> None:
    _close_qt_widgets()


@pytest.fixture(autouse=True)
def _cleanup_qt_widgets_after_test() -> None:
    yield
    _close_qt_widgets()


def _close_qt_widgets() -> None:
    if _QT_APP is None:
        return
    try:
        for widget in list(_QT_APP.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        _QT_APP.processEvents()
    except Exception:
        pass
    try:
        from core.acquisition.acquisition_service import shutdown_all_acquisition_services

        shutdown_all_acquisition_services()
    except Exception:
        pass
