import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from PySide6.QtWidgets import QApplication

from dmneditor.main_window import open_startup_windows


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Outline Editor")
    windows = open_startup_windows()  # kept alive until the event loop exits
    for i, window in enumerate(windows):
        if i:  # cascade extra recovery windows so they don't stack exactly
            window.move(window.x() + 30 * i, window.y() + 30 * i)
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
