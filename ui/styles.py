"""Hoja de estilos (QSS) de la aplicación, separada de la lógica de la ventana."""

DARK_QSS = """
QMainWindow, QWidget { background-color: #131722; color: #d1d4dc; font-family: -apple-system, Segoe UI, sans-serif; }
QPushButton { background-color: #1e222d; border: 1px solid #2a2e39; border-radius: 5px; padding: 6px 12px; color: #d1d4dc; }
QPushButton:hover { border-color: #8a742a; }
QPushButton:checked { border-color: #c9a227; color: #c9a227; background-color: rgba(201,162,39,0.12); }
QPushButton:disabled { color: #5b5e66; border-color: #22262f; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background-color: #1e222d; border: 1px solid #2a2e39; border-radius: 5px; padding: 4px 8px; color: #d1d4dc; }
QLabel { color: #9598a1; font-size: 12px; }
QGroupBox { border: 1px solid #2a2e39; border-radius: 6px; margin-top: 8px; padding-top: 10px; color: #c9a227; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; }
QTableWidget { background-color: #1a1e2b; gridline-color: #2a2e39; border: 1px solid #2a2e39; }
QHeaderView::section { background-color: #1e222d; color: #9598a1; border: none; padding: 4px; }
QSlider::groove:horizontal { background: #2a2e39; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #c9a227; width: 12px; margin: -5px 0; border-radius: 6px; }
QDockWidget { color: #c9a227; font-weight: 600; titlebar-close-icon: none; }
QDockWidget::title { background: #1a1e2b; padding: 6px 8px; border: 1px solid #2a2e39; }
QMainWindow::separator { background: #2a2e39; width: 3px; height: 3px; }
QMenuBar { background: #1a1e2b; color: #d1d4dc; border-bottom: 1px solid #2a2e39; }
QMenuBar::item:selected { background: #2a2e39; }
QMenu { background: #1a1e2b; color: #d1d4dc; border: 1px solid #2a2e39; }
QMenu::item:selected { background: #2a2e39; }
"""
