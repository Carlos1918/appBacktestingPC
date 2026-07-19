"""Backtest ICT/SMC — App de escritorio. Punto de entrada."""
import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.styles import DARK_QSS


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
