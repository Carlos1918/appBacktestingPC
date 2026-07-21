"""Backtest ICT/SMC — ventana principal."""
import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QLineEdit, QComboBox, QSlider, QCheckBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout, QCompleter,
    QDockWidget, QSizePolicy, QMessageBox, QDoubleSpinBox,
    QListWidget, QDialog, QDialogButtonBox, QInputDialog, QColorDialog
)
from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QColor, QAction

from chart.chart_widget import ChartWidget
from core import journal_store, session_store, pdf_export, stats as journal_stats
from core import mt5_data
from core.mt5_workers import FetchWorker, LiveTickWorker, CsvLoadWorker
from core.trading_account import TradingAccount
from core.formatting import format_price

# Sube este número cada vez que cambie la disposición por defecto de los paneles,
# para que las versiones guardadas antiguas no hereden una posición obsoleta.
LAYOUT_VERSION = 3


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backtest ICT/SMC — TraderMind MC")
        self.resize(1280, 720)

        self.trades = journal_store.load_trades()
        self.account = TradingAccount(10000.0)
        self._digits_cache = {}

        # Estado del modo en vivo: es el estado por defecto de la app siempre que
        # haya datos de MT5 cargados y no se esté haciendo un replay ciego. Se
        # apaga únicamente al fijar un punto de inicio de replay, y se reactiva
        # solo al terminar ese replay ("Finalizar Replay") o al llegar al final
        # del histórico revelado mientras se reproduce manualmente.
        self.live_mode_active = False
        self.live_busy = False
        self.live_source_is_mt5 = False
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self._poll_live)

        self.playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_step)

        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AnimatedDocks)

        # ================= CENTRAL: el gráfico, tan grande como se pueda =================
        central = QWidget()
        self.setCentralWidget(central)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(4, 4, 4, 4)

        self.chart = ChartWidget()
        self.chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chart.ohlc_hover.connect(self.on_ohlc_hover)
        self.chart.trade_touched.connect(self.on_trade_touched)
        self.chart.buy_clicked.connect(lambda: self.execute_market_order("buy"))
        self.chart.sell_clicked.connect(lambda: self.execute_market_order("sell"))
        self.chart.open_trade_changed.connect(self.refresh_open_banner)
        self.chart.step_back_requested.connect(lambda: self.on_step_back())
        self.chart.play_pause_requested.connect(lambda: self.toggle_play())
        self.chart.step_requested.connect(lambda: self.on_step())
        self.chart.lock_requested.connect(self.on_start_replay_here)
        self.chart.replay_locked.connect(self.on_replay_locked)
        self.chart.tool_changed.connect(self.set_tool)
        central_layout.addWidget(self.chart, stretch=1)

        self.ohlc_label = QLabel("")
        central_layout.addWidget(self.ohlc_label)

        self.last_close_label = QLabel("")
        central_layout.addWidget(self.last_close_label)

        # ================= DOCK: Controles (todo en una sola franja, ancho completo) =================
        dock_top = QDockWidget("Controles", self)
        dock_top.setObjectName("dock_controles")
        dock_top.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        top_widget = QWidget(); top_col = QVBoxLayout(top_widget)
        top_col.setSpacing(6)

        # --- fila 1: conexión MT5 ---
        mt5_row = QHBoxLayout()
        self.btn_connect = QPushButton("🔌 Conectar a MT5")
        self.btn_connect.clicked.connect(self.on_connect_mt5)
        self.mt5_status = QLabel("Sin conectar")
        self.mt5_status.setWordWrap(True)
        self.mt5_status.setMaximumWidth(180)
        self.symbol_combo = QComboBox()
        self.symbol_combo.setEditable(True)
        self.symbol_combo.setInsertPolicy(QComboBox.NoInsert)
        self.symbol_combo.setPlaceholderText("Símbolo (XAUUSD, EURJPY, Boom 1000...)")
        self.symbol_combo.setFixedWidth(190)
        self.symbol_combo.setEnabled(False)
        self.tf_combo = QComboBox()
        self.tf_combo.addItems(mt5_data.TIMEFRAMES)
        self.tf_combo.setCurrentText("M15")
        self.tf_combo.currentTextChanged.connect(self.on_tf_combo_changed)
        self.bars_spin = QSpinBox(); self.bars_spin.setRange(200, 20000); self.bars_spin.setValue(3000)
        self.bars_spin.setFixedWidth(75)
        self.btn_fetch = QPushButton("📥 Cargar desde MT5")
        self.btn_fetch.clicked.connect(lambda: self.on_fetch_mt5(preserve_position=False))
        self.btn_fetch.setEnabled(False)
        self.btn_load = QPushButton("📂 CSV manual")
        self.btn_load.setToolTip("Cargar un archivo CSV/TXT exportado de MT5 en vez de conectar en vivo.")
        self.btn_load.clicked.connect(self.on_load)
        self.symbol_field = QLineEdit(); self.symbol_field.setPlaceholderText("Símbolo (solo CSV)")
        self.symbol_field.setFixedWidth(120)
        self.status_label = QLabel("Sin datos cargados")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(220)
        for w in [self.btn_connect, self.mt5_status, QLabel("Símbolo:"), self.symbol_combo,
                  QLabel("TF:"), self.tf_combo, QLabel("Velas:"), self.bars_spin, self.btn_fetch,
                  self.btn_load, self.symbol_field, self.status_label]:
            mt5_row.addWidget(w)
        mt5_row.addStretch()
        top_col.addLayout(mt5_row)

        # --- fila 1b: cuenta simulada ---
        account_row = QHBoxLayout()
        account_row.addWidget(QLabel("Cuenta:"))
        self.balance_spin = QDoubleSpinBox(); self.balance_spin.setRange(10, 10_000_000)
        self.balance_spin.setDecimals(2); self.balance_spin.setValue(10000.0)
        self.balance_spin.setFixedWidth(100)
        self.btn_reset_account = QPushButton("🔄 Reiniciar cuenta")
        self.btn_reset_account.clicked.connect(self.on_reset_account)
        self.balance_label = QLabel("Balance: $10,000.00")
        self.balance_label.setStyleSheet("font-weight:600; color:#d1d4dc;")
        self.equity_label = QLabel("Equity: $10,000.00")
        self.equity_label.setStyleSheet("font-weight:600; color:#d1d4dc;")
        account_row.addWidget(self.balance_spin)
        account_row.addWidget(self.btn_reset_account)
        account_row.addSpacing(16)
        account_row.addWidget(self.balance_label)
        account_row.addSpacing(16)
        account_row.addWidget(self.equity_label)
        account_row.addSpacing(24)
        account_row.addWidget(QLabel("Lotaje:"))
        self.lot_spin = QDoubleSpinBox(); self.lot_spin.setRange(0.01, 100); self.lot_spin.setDecimals(2)
        self.lot_spin.setSingleStep(0.01); self.lot_spin.setValue(0.10)
        self.lot_spin.setFixedWidth(70)
        account_row.addWidget(self.lot_spin)
        account_row.addStretch()
        top_col.addLayout(account_row)

        # --- fila 2: replay ---
        toolbar = QHBoxLayout()
        self.btn_start_here = QPushButton("📍 Fijar inicio")
        self.btn_start_here.setCheckable(True)
        self.btn_start_here.setToolTip(
            "El precio se mantiene en vivo todo el tiempo, incluso si cambias de\n"
            "temporalidad. Este botón es la única forma de pasar a un replay ciego:\n"
            "arma el cursor y haces clic en la vela exacta donde quieres empezar."
        )
        self.btn_start_here.clicked.connect(self.on_start_replay_here)
        self.btn_step_back = QPushButton("⏮"); self.btn_step_back.clicked.connect(self.on_step_back)
        self.btn_play = QPushButton("▶ Reproducir"); self.btn_play.clicked.connect(self.toggle_play)
        self.btn_step = QPushButton("Siguiente ⏭"); self.btn_step.clicked.connect(self.on_step)
        self.speed_slider = QSlider(Qt.Horizontal); self.speed_slider.setRange(30, 1000); self.speed_slider.setValue(220)
        self.speed_slider.setFixedWidth(80)
        self.speed_slider.valueChanged.connect(self.on_speed_change)
        self.speed_label = QLabel("220ms")
        self.btn_live = QPushButton("📍 Ver precio actual"); self.btn_live.clicked.connect(self.on_go_live)
        self.btn_live.setToolTip("Centra la vista en la última vela (sin afectar el modo en vivo/replay).")
        self.btn_finish_replay = QPushButton("🔴 En Vivo")
        self.btn_finish_replay.setEnabled(False)
        self.btn_finish_replay.setToolTip(
            "El precio en vivo es el estado normal de la app — se actualiza solo cada\n"
            "1.5s con el precio real de MT5, incluso si cambias de símbolo o temporalidad.\n"
            "Este botón solo se activa durante un replay: termina el replay (comprobando\n"
            "el SL/TP de cualquier operación abierta en las velas que faltaban) y vuelve a vivo."
        )
        self.btn_finish_replay.setStyleSheet(
            "QPushButton { border-color:#26a69a; color:#26a69a; background: rgba(38,166,154,0.10); }"
            "QPushButton:enabled { border-color:#c9a227; color:#c9a227; background: rgba(201,162,39,0.12); }"
        )
        self.btn_finish_replay.clicked.connect(self.on_finish_replay)
        for w in [self.btn_start_here, self.btn_step_back, self.btn_play, self.btn_step,
                  self.speed_slider, self.speed_label, self.btn_live, self.btn_finish_replay]:
            toolbar.addWidget(w)
        toolbar.addStretch()
        top_col.addLayout(toolbar)

        # --- fila 3: herramientas de dibujo + EMA ---
        draw_row = QHBoxLayout()
        self.btn_cursor = QPushButton("Cursor"); self.btn_cursor.setCheckable(True); self.btn_cursor.setChecked(True)
        self.btn_cursor.setToolTip(
            "Arrastrar = mover el gráfico (funciona siempre, incluso sobre dibujos).\n"
            "Rueda del mouse = zoom. Cerca de una línea de SL/TP = arrastrarla.\n"
            "Shift + arrastrar sobre un dibujo = mover ese dibujo completo."
        )
        self.btn_line = QPushButton("— Horiz."); self.btn_line.setCheckable(True)
        self.btn_trend = QPushButton("╱ Tendencia"); self.btn_trend.setCheckable(True)
        self.btn_trend.setToolTip("Clic para iniciar, clic para terminar.")
        self.btn_rect = QPushButton("▭ Rectángulo"); self.btn_rect.setCheckable(True)
        self.btn_rect.setToolTip("Clic-clic para marcar una zona (FVG, order block, killzone...).")
        self.btn_fib = QPushButton("Fibonacci"); self.btn_fib.setCheckable(True)
        self.btn_fib.setToolTip("Clic para iniciar, clic para terminar.")
        self.btn_rr_long = QPushButton("R:R Long"); self.btn_rr_long.setCheckable(True)
        self.btn_rr_long.setStyleSheet("QPushButton:checked{border-color:#26a69a; color:#26a69a;}")
        self.btn_rr_long.setToolTip("Clic en la entrada, clic donde pondrías el SL — el TP se calcula solo con el ratio.")
        self.btn_rr_short = QPushButton("R:R Short"); self.btn_rr_short.setCheckable(True)
        self.btn_rr_short.setStyleSheet("QPushButton:checked{border-color:#ef5350; color:#ef5350;}")
        self.btn_rr_short.setToolTip("Clic en la entrada, clic donde pondrías el SL — el TP se calcula solo con el ratio.")
        self.rr_ratio_spin = QDoubleSpinBox(); self.rr_ratio_spin.setRange(0.5, 20); self.rr_ratio_spin.setSingleStep(0.5)
        self.rr_ratio_spin.setValue(2.0); self.rr_ratio_spin.setFixedWidth(60)
        self.rr_ratio_spin.setPrefix("1:")
        self.rr_ratio_spin.valueChanged.connect(self.on_rr_ratio_change)
        self.btn_clear = QPushButton("Borrar dibujos"); self.btn_clear.clicked.connect(self.on_clear_drawings)
        for btn, tool in [(self.btn_cursor, "cursor"), (self.btn_line, "line"), (self.btn_trend, "trend"),
                           (self.btn_rect, "rect"), (self.btn_fib, "fib"),
                           (self.btn_rr_long, "rr_long"), (self.btn_rr_short, "rr_short")]:
            btn.clicked.connect(lambda checked, t=tool: self.set_tool(t))
        self.ema1_chk = QCheckBox("EMA"); self.ema1_chk.stateChanged.connect(self.on_ema_change)
        self.ema1_spin = QSpinBox(); self.ema1_spin.setRange(2, 400); self.ema1_spin.setValue(20)
        self.ema1_spin.setFixedWidth(50)
        self.ema1_spin.valueChanged.connect(self.on_ema_change)
        self.ema2_chk = QCheckBox("EMA"); self.ema2_chk.stateChanged.connect(self.on_ema_change)
        self.ema2_spin = QSpinBox(); self.ema2_spin.setRange(2, 400); self.ema2_spin.setValue(50)
        self.ema2_spin.setFixedWidth(50)
        self.ema2_spin.valueChanged.connect(self.on_ema_change)
        self.chart_style_chk = QCheckBox("Ver en líneas")
        self.chart_style_chk.setToolTip("Alterna entre velas japonesas y una línea de precio de cierre.")
        self.chart_style_chk.stateChanged.connect(self.on_chart_style_change)
        self.btn_colors = QPushButton("🎨 Colores")
        self.btn_colors.setToolTip("Personalizar el color del fondo, las velas y los dibujos nuevos.")
        self.btn_colors.clicked.connect(self.on_edit_colors)
        for w in [self.btn_cursor, self.btn_line, self.btn_trend, self.btn_rect, self.btn_fib,
                  self.btn_rr_long, self.btn_rr_short, self.rr_ratio_spin, self.btn_clear,
                  self.ema1_chk, self.ema1_spin, self.ema2_chk, self.ema2_spin, self.chart_style_chk,
                  self.btn_colors]:
            draw_row.addWidget(w)
        draw_row.addStretch()
        top_col.addLayout(draw_row)

        # --- fila 4: ICT — herramientas de analisis ---
        ict_row = QHBoxLayout()
        ict_row.addWidget(QLabel("ICT:"))
        self.ict_fvg_chk = QCheckBox("FVG")
        self.ict_fvg_chk.stateChanged.connect(self.on_ict_change)
        self.ict_ob_chk = QCheckBox("Order Block")
        self.ict_ob_chk.stateChanged.connect(self.on_ict_change)
        self.ict_mss_chk = QCheckBox("MSS/CHoCH")
        self.ict_mss_chk.stateChanged.connect(self.on_ict_change)
        self.ict_liq_chk = QCheckBox("Liquidez")
        self.ict_liq_chk.stateChanged.connect(self.on_ict_change)
        self.ict_pd_chk = QCheckBox("Prem/Disc")
        self.ict_pd_chk.stateChanged.connect(self.on_ict_change)
        self.ict_ote_chk = QCheckBox("OTE")
        self.ict_ote_chk.stateChanged.connect(self.on_ict_change)
        self.ict_kz_chk = QCheckBox("Killzones")
        self.ict_kz_chk.stateChanged.connect(self.on_ict_change)
        self.ict_clear_btn = QPushButton("Limpiar deteccion")
        self.ict_clear_btn.clicked.connect(self.on_ict_clear)
        self.ict_status_label = QLabel("ICT inactivo")
        self.ict_status_label.setStyleSheet("color:#787b86; font-size:11px;")
        for w in [self.ict_fvg_chk, self.ict_ob_chk, self.ict_mss_chk, self.ict_liq_chk,
                  self.ict_pd_chk, self.ict_ote_chk, self.ict_kz_chk, self.ict_clear_btn]:
            ict_row.addWidget(w)
        ict_row.addWidget(self.ict_status_label)
        ict_row.addStretch()
        top_col.addLayout(ict_row)

        # --- fila 5: avanzar rápido + operación abierta ---
        scrub_row = QHBoxLayout()
        self.scrub_slider = QSlider(Qt.Horizontal); self.scrub_slider.setRange(0, 100)
        self.scrub_slider.valueChanged.connect(self.on_scrub)
        self.scrub_label = QLabel("vela 0 / 0")
        scrub_row.addWidget(QLabel("Avanzar rápido:"))
        scrub_row.addWidget(self.scrub_slider, stretch=1)
        scrub_row.addWidget(self.scrub_label)
        top_col.addLayout(scrub_row)

        self.open_trade_label = QLabel("")
        self.btn_close_manual = QPushButton("Cerrar manual al precio actual")
        self.btn_close_manual.clicked.connect(self.on_close_manual)
        self.btn_close_manual.setVisible(False)
        self.open_trade_label.setVisible(False)
        open_row = QHBoxLayout()
        open_row.addWidget(self.open_trade_label)
        open_row.addWidget(self.btn_close_manual)
        open_row.addStretch()
        top_col.addLayout(open_row)

        dock_top.setWidget(top_widget)
        self.addDockWidget(Qt.TopDockWidgetArea, dock_top)

        # ================= DOCK: Journal =================
        dock_journal = QDockWidget("3. Journal", self)
        dock_journal.setObjectName("dock_journal")
        dock_journal.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        journal_widget = QWidget(); journal_col = QVBoxLayout(journal_widget)

        self.stats_grid = QGridLayout()
        self.stat_labels = {}
        for i, key in enumerate(["Total", "Ganadas", "Perdidas", "Winrate", "Suma R", "Expectancy"]):
            lab = QLabel(key); lab.setStyleSheet("font-size:10px; text-transform:uppercase;")
            val = QLabel("0"); val.setStyleSheet("font-size:18px; font-weight:600; color:#d1d4dc;")
            self.stats_grid.addWidget(lab, 0, i)
            self.stats_grid.addWidget(val, 1, i)
            self.stat_labels[key] = val
        # Segunda fila: estadísticas avanzadas (profit factor, Sharpe por-trade,
        # rachas consecutivas, mejor/peor R) — ver core/stats.py.
        for i, key in enumerate(["Profit Factor", "Sharpe", "Racha Ganadora", "Racha Perdedora", "Mejor R", "Peor R"]):
            lab = QLabel(key); lab.setStyleSheet("font-size:10px; text-transform:uppercase;")
            val = QLabel("0"); val.setStyleSheet("font-size:15px; font-weight:600; color:#9598a1;")
            self.stats_grid.addWidget(lab, 2, i)
            self.stats_grid.addWidget(val, 3, i)
            self.stat_labels[key] = val
        journal_col.addLayout(self.stats_grid)

        top_row = QHBoxLayout()
        self.btn_export_pdf = QPushButton("📄 Exportar PDF")
        self.btn_export_pdf.clicked.connect(self.on_export_pdf)
        self.btn_clear_all = QPushButton("Borrar todo el journal")
        self.btn_clear_all.clicked.connect(self.on_clear_journal)
        top_row.addWidget(self.btn_export_pdf); top_row.addStretch(); top_row.addWidget(self.btn_clear_all)
        journal_col.addLayout(top_row)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Símbolo", "Dir", "Entrada", "SL", "TP", "Salida", "Resultado", "R", "P&L", "Nota"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        journal_col.addWidget(self.table)

        dock_journal.setWidget(journal_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock_journal)

        # ── menú Sesión ──
        session_menu = self.menuBar().addMenu("Sesión")
        save_action = QAction("💾 Guardar sesión...", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.on_save_session)
        load_action = QAction("📂 Cargar sesión...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.on_load_session)
        session_menu.addAction(save_action)
        session_menu.addAction(load_action)

        self.view_menu = self.menuBar().addMenu("Ver")
        self.view_menu.addAction(dock_top.toggleViewAction())
        self.view_menu.addAction(dock_journal.toggleViewAction())
        self.view_menu.addSeparator()
        restore_action = self.view_menu.addAction("Restaurar diseño por defecto")
        restore_action.triggered.connect(lambda: self.restore_default_layout(dock_top, dock_journal))

        self.settings = QSettings("TraderMindMC", "BacktestICT")
        self._load_theme_from_settings()
        # Si el diseño guardado es de una versión anterior de la app (con otra
        # disposición de paneles), lo ignoramos y aplicamos el nuevo por defecto
        # en vez de heredar una posición que ya no tiene sentido.
        saved_layout_version = self.settings.value("layout_version", 0, type=int)
        if saved_layout_version < LAYOUT_VERSION:
            self.settings.remove("windowState")
            self.settings.remove("geometry")
            self.settings.setValue("layout_version", LAYOUT_VERSION)
        saved_state = self.settings.value("windowState")
        saved_geometry = self.settings.value("geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        if saved_state is not None:
            self.restoreState(saved_state)
        else:
            self.restore_default_layout(dock_top, dock_journal)

        self._fit_window_to_screen()

        self.refresh_journal()
        self.update_equity_display()
        self._update_live_button()

    def _fit_window_to_screen(self):
        """Asegura que la ventana quede completa dentro de la pantalla actual —
        necesario porque un diseño guardado en una pantalla más grande (o un
        segundo monitor que ya no está conectado) podría dejarla parcialmente
        fuera de vista. Qt puede negarse a encoger por debajo de lo que necesitan
        los paneles para mostrarse, así que primero intentamos encoger y luego
        reposicionamos usando el tamaño que realmente quedó aplicado."""
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        target_w = min(self.width(), avail.width())
        target_h = min(self.height(), avail.height())
        if target_w != self.width() or target_h != self.height():
            self.resize(target_w, target_h)

        geo = self.geometry()
        new_x = min(max(geo.x(), avail.x()), avail.x() + avail.width() - geo.width())
        new_y = min(max(geo.y(), avail.y()), avail.y() + avail.height() - geo.height())
        new_x = max(new_x, avail.x())
        new_y = max(new_y, avail.y())
        self.move(new_x, new_y)

    def closeEvent(self, event):
        self.live_timer.stop()
        # Si hay un hilo de carga en curso (MT5, CSV o sondeo en vivo) y la
        # ventana se cierra sin esperarlo, Qt destruye el QThread mientras el
        # hilo real sigue vivo ("QThread: Destroyed while thread is still
        # running") — puede colgar el cierre o crashear. Se le da un margen
        # corto para terminar solo; si no llega a tiempo, se pide que se
        # interrumpa antes de seguir con el cierre.
        for attr in ("_fetch_worker", "_csv_worker", "_live_worker"):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        mt5_data.disconnect()
        super().closeEvent(event)

    def restore_default_layout(self, dock_top, dock_journal):
        for dock in (dock_top, dock_journal):
            dock.setFloating(False)
            dock.show()
        self.addDockWidget(Qt.TopDockWidgetArea, dock_top)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock_journal)
        self.resizeDocks([dock_journal], [260], Qt.Vertical)

    # ---------- MT5 ----------
    def on_connect_mt5(self):
        self.mt5_status.setText("Conectando…")
        QApplication.processEvents()
        ok, err = mt5_data.connect()
        if not ok:
            self.mt5_status.setText("Error de conexión")
            QMessageBox.warning(self, "No se pudo conectar a MT5", err)
            return
        symbols = mt5_data.list_symbols()
        if not symbols:
            self.mt5_status.setText("Conectado, sin símbolos")
            QMessageBox.information(self, "Market Watch vacío",
                                     "Se conectó a MT5 pero no hay símbolos visibles en el Market Watch. "
                                     "Agrega al menos uno (ej. XAUUSD) desde MT5 y vuelve a conectar.")
            return
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols)
        self.symbol_combo.setEnabled(True)
        completer = QCompleter(symbols, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.symbol_combo.setCompleter(completer)
        self.btn_fetch.setEnabled(True)
        self.mt5_status.setText(f"Conectado — {len(symbols)} símbolos disponibles")

    def on_tf_combo_changed(self, text):
        if not self.btn_fetch.isEnabled():
            return
        if not self.symbol_combo.currentText().strip():
            return
        if not self.chart.base_candles:
            return
        self.on_fetch_mt5(preserve_position=True)

    def on_fetch_mt5(self, preserve_position=False):
        symbol = self.symbol_combo.currentText().strip()
        if not symbol:
            QMessageBox.warning(self, "Falta símbolo", "Elige o escribe un símbolo primero.")
            return
        tf = self.tf_combo.currentText()
        count = self.bars_spin.value()

        # Si estamos en medio de un replay y solo cambia el timeframe (mismo símbolo),
        # recordamos en qué momento estábamos parados para reubicarnos en la nueva serie.
        same_symbol = self.symbol_field.text().strip().upper() == symbol.upper()
        keep_position = preserve_position and same_symbol and self.chart.base_candles and self.chart.is_bounded()
        preserved_time = None
        preserved_trade = None
        preserved_view_count = None
        if keep_position:
            idx = min(self.chart.reveal_index, len(self.chart.base_candles)) - 1
            preserved_time = self.chart.base_candles[idx]["t"]
            preserved_trade = self.chart.open_trade
            preserved_view_count = self.chart.view_count

        # Los dibujos (líneas, tendencias, rectángulos, fibs, cajas R:R) se conservan
        # siempre que sea el mismo símbolo, sin importar si estamos en replay o no.
        preserved_drawings = self.chart.export_drawings() if (same_symbol and self.chart.base_candles) else None

        # El precio en vivo se mantiene mientras se carga (el candado de mt5_data
        # serializa cualquier llamada del sondeo en vivo con esta descarga, así que
        # no hace falta pausarlo ni deshabilitar el combo de temporalidad/símbolo).
        self.status_label.setText("Cargando…")
        self._set_data_controls_enabled(False)

        # Guardamos todo lo que el callback va a necesitar cuando el hilo termine.
        self._pending_symbol = symbol
        self._pending_tf = tf
        self._pending_preserved_time = preserved_time
        self._pending_preserved_trade = preserved_trade
        self._pending_preserved_view_count = preserved_view_count
        self._pending_preserved_drawings = preserved_drawings

        if preserved_time is not None:
            # Pide datos centrados en el punto que queremos conservar — así el rango
            # cubierto siempre incluye ese momento, sin importar cuánto más corto sea
            # el período que cubrirían las mismas N velas en el nuevo timeframe.
            try:
                preserved_dt = datetime.datetime.strptime(preserved_time, "%Y.%m.%d %H:%M")
            except ValueError:
                preserved_dt = None
            if preserved_dt is not None:
                half_window = datetime.timedelta(seconds=mt5_data.TF_SECONDS.get(tf, 900) * count / 2)
                date_from = preserved_dt - half_window
                date_to = preserved_dt + half_window
                self._fetch_worker = FetchWorker("range", symbol, tf, date_from=date_from, date_to=date_to)
            else:
                self._fetch_worker = FetchWorker("count", symbol, tf, count=count)
        else:
            self._fetch_worker = FetchWorker("count", symbol, tf, count=count)

        self._fetch_worker.finished_ok.connect(self._on_fetch_ok)
        self._fetch_worker.finished_err.connect(self._on_fetch_err)
        self._fetch_worker.start()

    def _set_data_controls_enabled(self, enabled):
        for w in [self.btn_connect, self.btn_fetch, self.tf_combo, self.symbol_combo,
                  self.bars_spin, self.btn_load]:
            w.setEnabled(enabled)

    def _on_fetch_err(self, err):
        self._set_data_controls_enabled(True)
        self.status_label.setText("Error al cargar")
        QMessageBox.warning(self, "No se pudo cargar el histórico", err)

    def _on_fetch_ok(self, candles):
        self._set_data_controls_enabled(True)
        symbol = self._pending_symbol
        tf = self._pending_tf
        preserved_time = self._pending_preserved_time
        preserved_trade = self._pending_preserved_trade
        preserved_view_count = self._pending_preserved_view_count
        preserved_drawings = self._pending_preserved_drawings

        self.chart.set_candles(candles)
        self.symbol_field.setText(symbol)
        self.chart.price_digits = self._get_symbol_digits(symbol)

        if preserved_drawings is not None:
            self.chart.import_drawings(preserved_drawings, candles, tf_seconds=mt5_data.TF_SECONDS.get(tf, 900))

        if preserved_time is not None:
            new_idx = self._find_index_at_or_after(candles, preserved_time)
            self.chart.lock_replay_here(new_idx + 1)
            if preserved_view_count:
                self.chart.view_count = min(preserved_view_count, self.chart.reveal_index)
                self.chart.view_start = max(0, self.chart.reveal_index - self.chart.view_count + self.chart._right_margin())
            self.chart.open_trade = preserved_trade
            self.refresh_open_banner()
            self.chart.repaint()
            self.status_label.setText(f"{symbol} ({tf}) — {len(candles)} velas · posición del replay conservada")
        else:
            self.chart.repaint()
            self.status_label.setText(f"{symbol} ({tf}) — {len(candles)} velas reales de MT5")

        self.update_last_close()
        self._reset_controls_after_load(len(candles))
        self.chart.setFocus()

        self.chart.tf_seconds = mt5_data.TF_SECONDS.get(tf, 900)
        self.live_source_is_mt5 = True
        # El precio en vivo es el estado por defecto: se reactiva solo si no
        # estamos preservando una posición de replay (es decir, si el gráfico
        # queda totalmente abierto tras esta carga). Si sí veníamos de un
        # replay, `_activate_live_mode` no hace nada porque el gráfico sigue
        # acotado — el replay continúa exactamente donde estaba.
        self._activate_live_mode()
        self._update_live_button()

    def _get_symbol_digits(self, symbol):
        if symbol not in self._digits_cache:
            try:
                self._digits_cache[symbol] = mt5_data.get_symbol_digits(symbol)
            except Exception:
                self._digits_cache[symbol] = None
        return self._digits_cache[symbol]

    @staticmethod
    def _find_index_at_or_after(candles, time_str):
        for i, c in enumerate(candles):
            if c["t"] >= time_str:
                return i
        return len(candles) - 1 if candles else 0

    # ---------- CSV manual ----------
    def on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir archivo", "", "CSV/TXT (*.csv *.txt);;Todos (*.*)")
        if not path:
            return
        self.status_label.setText("Leyendo archivo…")
        self._set_data_controls_enabled(False)
        self._pending_csv_path = path
        self._csv_worker = CsvLoadWorker(path)
        self._csv_worker.finished_ok.connect(self._on_csv_ok)
        self._csv_worker.finished_err.connect(self._on_csv_err)
        self._csv_worker.start()

    def _on_csv_err(self, err):
        self._set_data_controls_enabled(True)
        self.status_label.setText("Error al leer el archivo")
        QMessageBox.warning(self, "No se pudo leer el archivo", err)

    def _on_csv_ok(self, candles):
        self._set_data_controls_enabled(True)
        if len(candles) < 90:
            self.status_label.setText("Datos insuficientes")
            QMessageBox.warning(self, "Datos insuficientes", f"Solo se encontraron {len(candles)} velas válidas.")
            return
        self.chart.set_candles(candles)
        self.chart.price_digits = None  # sin símbolo de MT5 no hay dígitos reales que consultar
        self.status_label.setText(f"{self.symbol_field.text() or 'Símbolo'} — {len(candles)} velas")
        self._reset_controls_after_load(len(candles))
        self.live_source_is_mt5 = False
        self._disable_live_mode()
        self._update_live_button()

    def _reset_controls_after_load(self, total_candles):
        for w in [self.btn_play, self.btn_step, self.btn_step_back, self.scrub_slider, self.chart.buy_btn, self.chart.sell_btn]:
            w.setEnabled(True)
        self.scrub_slider.blockSignals(True)
        self.scrub_slider.setRange(0, total_candles - 1)
        self.scrub_slider.setValue(self.chart.reveal_index)
        self.scrub_slider.blockSignals(False)
        self.update_scrub_label()

    # ---------- fijar el punto de inicio del replay ----------
    def ensure_replay_locked(self):
        """Si el gráfico todavía está totalmente abierto (sin replay activo), lo fija
        justo donde el usuario esté parado ahora mismo, y empieza el modo ciego desde ahí."""
        if not self.chart.base_candles:
            return False
        if self.chart.is_bounded():
            return True
        self._disable_live_mode()
        idx = self.chart.last_hover_idx
        if idx is None:
            idx = self.chart.view_start + self.chart.view_count
        self.chart.lock_replay_here(idx)
        self.refresh_open_banner()
        self.scrub_slider.blockSignals(True)
        self.scrub_slider.setRange(0, len(self.chart.base_candles) - 1)
        self.scrub_slider.setValue(self.chart.reveal_index)
        self.scrub_slider.blockSignals(False)
        self.update_scrub_label()
        self.update_last_close()
        return True

    def on_start_replay_here(self):
        if not self.chart.base_candles:
            return
        if self.chart.open_trade:
            if QMessageBox.question(
                self, "Operación abierta",
                "Tienes una operación abierta. Elegir un nuevo punto de inicio la descarta "
                "(no se registra en el journal). ¿Continuar?"
            ) != QMessageBox.Yes:
                return
        self.pause()
        self._disable_live_mode()
        # Vuelve a mostrar todo el histórico para poder elegir un punto nuevo,
        # incluso si ya habías fijado uno antes.
        self.chart.reveal_index = len(self.chart.base_candles)
        self.chart.open_trade = None
        self.refresh_open_banner()
        self.chart.update()
        self.set_tool("lock")

    # ---------- modo en vivo ----------
    # El precio en vivo es el estado por defecto de la app: se activa solo con
    # datos de MT5 (nunca con CSV) y solo cuando el gráfico no está acotado por
    # un replay. La única forma de apagarlo es iniciar un replay ("Fijar inicio");
    # la única forma de reactivarlo es terminarlo ("Finalizar Replay") o llegar
    # al final del histórico revelado reproduciendo manualmente.
    def _activate_live_mode(self):
        if not self.chart.base_candles or not self.live_source_is_mt5:
            return
        if self.chart.is_bounded():
            return
        self.live_mode_active = True
        self._set_playback_controls_enabled(False)
        self.live_timer.start(1500)
        self._update_live_button()

    def _disable_live_mode(self):
        self.live_mode_active = False
        self.live_timer.stop()
        self._set_playback_controls_enabled(True)
        self._update_live_button()

    def _set_playback_controls_enabled(self, enabled):
        """Reproducir/Siguiente/Atrás y el slider de avance solo tienen sentido
        durante un replay — se deshabilitan mientras el precio está en vivo, en vez
        de solo ignorar el clic en silencio, para que sea evidente de un vistazo.
        'Fijar inicio' NO está en esta lista a propósito: debe seguir siendo
        clicable en cualquier momento, porque es la única forma de pasar a replay."""
        for w in [self.btn_play, self.btn_step, self.btn_step_back, self.scrub_slider]:
            w.setEnabled(enabled)

    def _update_live_button(self):
        if not self.chart.base_candles:
            self.btn_finish_replay.setText("🔴 En Vivo")
            self.btn_finish_replay.setEnabled(False)
            return
        if self.chart.is_bounded():
            self.btn_finish_replay.setText("⏹ Finalizar Replay")
            self.btn_finish_replay.setEnabled(True)
            return
        if not self.live_source_is_mt5:
            self.btn_finish_replay.setText("Modo CSV (sin vivo)")
            self.btn_finish_replay.setEnabled(False)
            return
        self.btn_finish_replay.setText("🔴 En Vivo (activo)" if self.live_mode_active else "🔴 En Vivo")
        self.btn_finish_replay.setEnabled(False)

    def on_finish_replay(self):
        """Termina el replay ciego actual y vuelve al modo en vivo. Antes de volver,
        adelanta las velas que faltaban por revelar comprobando el SL/TP de la
        operación abierta en el camino (si existe) — igual que hacía la antigua
        'Saltar a En Vivo': no descarta la operación, la deja seguir viva si no
        se cerró en ese tramo."""
        if not self.chart.base_candles or not self.chart.is_bounded():
            return
        self.pause()
        while self.chart.is_bounded():
            self.chart.step()
        self.refresh_open_banner()
        self.update_scrub_label()
        self.update_last_close()
        self._activate_live_mode()

    def _poll_live(self):
        if self.live_busy or not self.live_mode_active:
            return
        if not self.chart.base_candles or self.chart.is_bounded():
            self._disable_live_mode()
            return
        symbol = self.symbol_field.text().strip()
        tf = self.tf_combo.currentText()
        if not symbol:
            return
        self.live_busy = True
        self._live_worker = LiveTickWorker(symbol, tf, count=2)
        self._live_worker.got_bars.connect(self._on_live_bars)
        self._live_worker.failed.connect(self._on_live_failed)
        self._live_worker.start()

    def _on_live_failed(self, err):
        self.live_busy = False

    def _on_live_bars(self, bars):
        self.live_busy = False
        if not bars or not self.live_mode_active or self.chart.is_bounded():
            return
        latest = bars[-1]
        base = self.chart.base_candles
        if base and base[-1]["t"] == latest["t"]:
            base[-1] = latest
        else:
            base.append(latest)
            self.chart.reveal_index = len(base)
        if self.chart.open_trade:
            self.chart._check_trade_close(latest)
        if self.chart.auto_follow:
            self.chart.view_start = self.chart._max_view_start(len(base))
        self.chart.update()
        self.update_last_close()
        self.refresh_open_banner()

    def on_replay_locked(self):
        self._disable_live_mode()
        self.refresh_open_banner()
        self.scrub_slider.blockSignals(True)
        self.scrub_slider.setRange(0, len(self.chart.base_candles) - 1)
        self.scrub_slider.setValue(self.chart.reveal_index)
        self.scrub_slider.blockSignals(False)
        self.update_scrub_label()
        self.update_last_close()
        self.set_tool("cursor")

    # ---------- tools ----------
    def set_tool(self, tool):
        self.chart.tool = tool
        self.chart.drag_start = None
        self.chart.drag_current = None
        for b, t in [(self.btn_cursor, "cursor"), (self.btn_line, "line"), (self.btn_trend, "trend"),
                     (self.btn_rect, "rect"), (self.btn_fib, "fib"),
                     (self.btn_rr_long, "rr_long"), (self.btn_rr_short, "rr_short")]:
            b.setChecked(t == tool)
        self.btn_start_here.setChecked(tool == "lock")
        self.chart.set_lock_visual(tool == "lock")
        cursors = {"lock": Qt.SplitHCursor, "line": Qt.CrossCursor, "trend": Qt.CrossCursor,
                   "rect": Qt.CrossCursor, "fib": Qt.CrossCursor,
                   "rr_long": Qt.CrossCursor, "rr_short": Qt.CrossCursor}
        self.chart.setCursor(cursors.get(tool, Qt.ArrowCursor))

    def on_rr_ratio_change(self, val):
        self.chart.rr_ratio = val

    def on_clear_drawings(self):
        self.chart.clear_drawings()

    def on_go_live(self):
        self.chart.go_live()

    def on_ema_change(self):
        self.chart.ema_on = self.ema1_chk.isChecked()
        self.chart.ema_period = self.ema1_spin.value()
        self.chart.ema2_on = self.ema2_chk.isChecked()
        self.chart.ema2_period = self.ema2_spin.value()
        self.chart.update()

    def on_chart_style_change(self):
        self.chart.chart_style = "line" if self.chart_style_chk.isChecked() else "candles"
        self.chart.update()

    def _save_theme_to_settings(self, theme):
        for key, value in theme.items():
            self.settings.setValue(f"chart_theme/{key}", value)

    def _load_theme_from_settings(self):
        theme = self.chart.get_theme()
        for key in theme:
            val = self.settings.value(f"chart_theme/{key}")
            if val:
                theme[key] = val
        self.chart.apply_theme(theme)

    def on_edit_colors(self):
        theme = dict(self.chart.get_theme())
        default_theme = {"bg": "#1e222d", "up": "#26a69a", "down": "#ef5350",
                          "hline": "#9598a1", "trend": "#e0a800", "rect": "#c9a227"}
        fields = [
            ("bg", "Fondo del gráfico"),
            ("up", "Velas alcistas"),
            ("down", "Velas bajistas"),
            ("hline", "Línea horizontal (nuevas)"),
            ("trend", "Línea de tendencia (nuevas)"),
            ("rect", "Rectángulo (nuevas)"),
        ]

        dialog = QDialog(self)
        dialog.setWindowTitle("Personalizar colores")
        layout = QVBoxLayout(dialog)
        grid = QGridLayout()
        layout.addLayout(grid)
        swatches = {}

        def swatch_style(hexcolor):
            return f"background-color: {hexcolor}; border: 1px solid #555;"

        def make_pick_handler(key, btn):
            def pick():
                color = QColorDialog.getColor(QColor(theme[key]), dialog, "Elegir color")
                if color.isValid():
                    theme[key] = color.name()
                    btn.setStyleSheet(swatch_style(theme[key]))
                    self.chart.apply_theme(theme)
                    self._save_theme_to_settings(theme)
            return pick

        for row, (key, label) in enumerate(fields):
            grid.addWidget(QLabel(label), row, 0)
            btn = QPushButton()
            btn.setFixedSize(60, 24)
            btn.setStyleSheet(swatch_style(theme[key]))
            btn.clicked.connect(make_pick_handler(key, btn))
            swatches[key] = btn
            grid.addWidget(btn, row, 1)

        def on_reset():
            theme.update(default_theme)
            for key, btn in swatches.items():
                btn.setStyleSheet(swatch_style(theme[key]))
            self.chart.apply_theme(theme)
            self._save_theme_to_settings(theme)

        reset_btn = QPushButton("Restaurar valores por defecto")
        reset_btn.clicked.connect(on_reset)
        layout.addWidget(reset_btn)

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def on_ict_change(self):
        self.chart.ict_show_fvg = self.ict_fvg_chk.isChecked()
        self.chart.ict_show_ob = self.ict_ob_chk.isChecked()
        self.chart.ict_show_mss = self.ict_mss_chk.isChecked()
        self.chart.ict_show_liquidity = self.ict_liq_chk.isChecked()
        self.chart.ict_show_pd = self.ict_pd_chk.isChecked()
        self.chart.ict_show_ote = self.ict_ote_chk.isChecked()
        self.chart.ict_show_killzones = self.ict_kz_chk.isChecked()
        self.chart._ict_cache = {}
        self.chart.update()
        active = [k for k, v in [("FVG",self.ict_fvg_chk),("OB",self.ict_ob_chk),
                   ("MSS",self.ict_mss_chk),("LQD",self.ict_liq_chk),
                   ("P/D",self.ict_pd_chk),("OTE",self.ict_ote_chk),
                   ("KZ",self.ict_kz_chk)] if v.isChecked()]
        self.ict_status_label.setText("ICT: " + ", ".join(active) if active else "ICT inactivo")

    def on_ict_clear(self):
        for chk in [self.ict_fvg_chk, self.ict_ob_chk, self.ict_mss_chk,
                     self.ict_liq_chk, self.ict_pd_chk, self.ict_ote_chk, self.ict_kz_chk]:
            chk.setChecked(False)
        self.chart._ict_cache = {}
        self.chart.update()

    def on_ohlc_hover(self, text):
        self.ohlc_label.setText(text)

    # ---------- replay ----------
    def toggle_play(self):
        if self.playing:
            self.pause()
            return
        if self.live_mode_active:
            QMessageBox.information(
                self, "Estás en vivo",
                "Ya estás viendo el precio en vivo — no hay nada que reproducir.\n\n"
                "Si quieres hacer un backtest histórico, usa '📍 Fijar inicio' para "
                "elegir a propósito el punto exacto donde quieres empezar."
            )
            return
        if not self.ensure_replay_locked():
            return
        self.playing = True
        self.btn_play.setText("⏸ Pausar")
        self.chart.set_playing_visual(True)
        self.timer.start(self.speed_slider.value())

    def pause(self):
        self.playing = False
        self.timer.stop()
        self.btn_play.setText("▶ Reproducir")
        self.chart.set_playing_visual(False)

    def on_step(self):
        if not self.chart.base_candles:
            return
        if self.live_mode_active:
            return
        if not self.ensure_replay_locked():
            return
        ok = self.chart.step()
        if not ok:
            self.pause()
            self._maybe_resume_live_at_edge()
        self.update_scrub_label()
        self.update_last_close()
        self.refresh_open_banner()

    def _maybe_resume_live_at_edge(self):
        """El replay llegó al final de los datos cargados — ya no hay nada más que
        revelar, así que en vez de dejar el gráfico congelado, retoma el modo en
        vivo automáticamente (si los datos vienen de MT5 y no de un CSV manual)."""
        if self.live_source_is_mt5 and not self.chart.is_bounded():
            self._activate_live_mode()

    def on_step_back(self):
        self.pause()
        self.chart.step_back()
        self.update_scrub_label()
        self.update_last_close()

    def on_speed_change(self, val):
        self.speed_label.setText(f"{val}ms")
        if self.playing:
            self.timer.start(val)

    def on_scrub(self, val):
        if not self.chart.base_candles:
            return
        self.pause()
        new_index = max(self.chart.view_count, val)
        if self.chart.open_trade and new_index > self.chart.reveal_index:
            # A diferencia de step()/on_finish_replay(), esto puede saltar varias
            # velas de golpe — si hay una operación abierta, hay que recorrerlas
            # una por una comprobando el SL/TP, si no el cierre real se pierde
            # (el trade queda "abierto" en el journal aunque el precio ya lo haya
            # tocado en alguna de las velas saltadas).
            end = min(new_index, len(self.chart.base_candles))
            for idx in range(self.chart.reveal_index, end):
                candle = self.chart.base_candles[idx]
                self.chart.reveal_index = idx + 1
                if self.chart.open_trade:
                    self.chart._check_trade_close(candle)
                if not self.chart.open_trade:
                    break
        else:
            self.chart.reveal_index = new_index
        if self.chart.is_bounded():
            self._disable_live_mode()
        self.chart.update()
        self.update_scrub_label()
        self.update_last_close()
        self.refresh_open_banner()

    def update_scrub_label(self):
        total = len(self.chart.base_candles)
        self.scrub_label.setText(f"vela {self.chart.reveal_index} / {total}")
        self.scrub_slider.blockSignals(True)
        self.scrub_slider.setValue(self.chart.reveal_index)
        self.scrub_slider.blockSignals(False)

    def update_last_close(self):
        if not self.chart.base_candles:
            return
        idx = min(self.chart.reveal_index, len(self.chart.base_candles)) - 1
        c = self.chart.base_candles[idx]
        self.last_close_label.setText(
            f"Última vela: {c['t']}  ·  Close: {format_price(c['c'], self.chart.price_digits)}"
        )

    # ---------- trades ----------
    def execute_market_order(self, direction):
        """Ejecuta la orden a mercado al instante — sin preguntar SL/TP, igual que un
        clic de BUY/SELL en MT5. El SL y el TP aparecen ya puestos (a una distancia
        por defecto) y se pueden arrastrar directamente sobre el gráfico."""
        if not self.chart.base_candles:
            return
        if self.chart.open_trade:
            QMessageBox.information(self, "Operación abierta", "Ya tienes una operación abierta. Ciérrala antes de abrir otra.")
            return
        if self.live_mode_active:
            # En vivo no fijamos ningún punto de replay — se opera sobre el precio real
            # corriente y el gráfico se sigue actualizando solo.
            pass
        else:
            self.pause()
            if not self.ensure_replay_locked():
                return

        symbol = self.symbol_field.text() or "N/D"
        entry = self.chart.current_close()
        dist = self.chart.default_stop_distance()
        sl = entry - dist if direction == "buy" else entry + dist
        tp = entry + dist if direction == "buy" else entry - dist
        idx = min(self.chart.reveal_index, len(self.chart.base_candles)) - 1

        self.chart.open_trade = {
            "dir": direction, "entry": entry, "sl": sl, "tp": tp,
            "note": "", "entry_time": self.chart.base_candles[idx]["t"],
            "symbol": symbol, "volume": self.lot_spin.value(),
            "contract_size": self.account.get_contract_size(symbol),
            "digits": self.chart.price_digits,
        }
        self.chart.update()
        self.refresh_open_banner()

    def refresh_open_banner(self):
        t = self.chart.open_trade
        if not t:
            self.open_trade_label.setVisible(False)
            self.btn_close_manual.setVisible(False)
            self.update_equity_display()
            return
        self.open_trade_label.setVisible(True)
        self.btn_close_manual.setVisible(True)
        arrow = "▲ BUY" if t["dir"] == "buy" else "▼ SELL"
        color = "#26a69a" if t["dir"] == "buy" else "#ef5350"
        digits = self.chart.price_digits
        pnl = TradingAccount.compute_pnl(t, self.chart.current_close())
        pnl_color = "#26a69a" if pnl >= 0 else "#ef5350"
        self.open_trade_label.setStyleSheet(f"color:{color}; font-family: monospace;")
        self.open_trade_label.setText(
            f"{arrow} {t['volume']:.2f} lotes — Entrada {format_price(t['entry'], digits)}"
            f"  SL {format_price(t['sl'], digits)}  TP {format_price(t['tp'], digits)}"
            f"   ·   P&L flotante: {pnl:+.2f}"
        )
        self.update_equity_display(pnl)

    def update_equity_display(self, floating_pnl=0.0):
        self.balance_label.setText(f"Balance: ${self.account.balance:,.2f}")
        equity = self.account.balance + floating_pnl
        self.equity_label.setText(f"Equity: ${equity:,.2f}")
        self.equity_label.setStyleSheet(
            "font-weight:600; color:" + ("#26a69a" if floating_pnl >= 0 else "#ef5350") + ";"
        )

    def on_reset_account(self):
        if self.chart.open_trade:
            QMessageBox.information(self, "Operación abierta", "Cierra la operación abierta antes de reiniciar la cuenta.")
            return
        self.account.reset(self.balance_spin.value())
        self.update_equity_display()

    def on_close_manual(self):
        if not self.chart.open_trade:
            return
        idx = min(self.chart.reveal_index, len(self.chart.base_candles)) - 1
        exit_price = self.chart.current_close()
        exit_time = self.chart.base_candles[idx]["t"]
        r = TradingAccount.compute_r(self.chart.open_trade, exit_price)
        result = "Ganada" if r >= 0 else "Perdida"
        self._finalize_trade(exit_price, result, exit_time)

    def on_trade_touched(self, result, exit_price, exit_time):
        self._finalize_trade(exit_price, result, exit_time)

    def _finalize_trade(self, exit_price, result, exit_time):
        t = self.chart.open_trade
        if not t:
            return
        r = TradingAccount.compute_r(t, exit_price)
        pnl = TradingAccount.compute_pnl(t, exit_price)
        self.account.apply_pnl(pnl)
        trade = {
            "id": int(datetime.datetime.now().timestamp() * 1000),
            "symbol": t["symbol"], "dir": t["dir"], "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
            "exit": exit_price, "r": r, "pnl": pnl, "result": result, "note": t.get("note", ""),
            "entry_time": t["entry_time"], "exit_time": exit_time, "digits": t.get("digits"),
        }
        self.trades.insert(0, trade)
        journal_store.save_trades(self.trades)
        self.chart.open_trade = None
        self.chart.update()
        self.refresh_open_banner()
        self.refresh_journal()

    # ---------- journal ----------
    def on_clear_journal(self):
        if QMessageBox.question(self, "Confirmar", "¿Borrar todas las operaciones del journal?") == QMessageBox.Yes:
            self.trades = []
            journal_store.save_trades(self.trades)
            self.refresh_journal()

    def refresh_journal(self):
        self.table.setRowCount(len(self.trades))
        for row, t in enumerate(self.trades):
            digits = t.get("digits")
            values = [
                t.get("entry_time", ""), t["symbol"], "▲ Buy" if t["dir"] == "buy" else "▼ Sell",
                format_price(t['entry'], digits), format_price(t['sl'], digits),
                format_price(t['tp'], digits), format_price(t['exit'], digits),
                t["result"], f"{t['r']:.2f}R", f"{t.get('pnl', 0):+.2f}", t.get("note", ""),
            ]
            color = QColor("#26a69a") if t["result"] == "Ganada" else (QColor("#ef5350") if t["result"] == "Perdida" else QColor("#d1d4dc"))
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == 7:
                    item.setForeground(color)
                self.table.setItem(row, col, item)
        self.refresh_stats()

    def refresh_stats(self):
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t["result"] == "Ganada")
        losses = sum(1 for t in self.trades if t["result"] == "Perdida")
        winrate = (wins / total * 100) if total else 0
        sum_r = sum(t["r"] for t in self.trades)
        expectancy = (sum_r / total) if total else 0
        self.stat_labels["Total"].setText(str(total))
        self.stat_labels["Ganadas"].setText(str(wins))
        self.stat_labels["Perdidas"].setText(str(losses))
        self.stat_labels["Winrate"].setText(f"{winrate:.1f}%")
        self.stat_labels["Suma R"].setText(f"{sum_r:.2f}R")
        self.stat_labels["Expectancy"].setText(f"{expectancy:.2f}R")

        adv = journal_stats.compute_advanced_stats(self.trades)
        pf = adv["profit_factor"]
        self.stat_labels["Profit Factor"].setText("∞" if pf == float("inf") else f"{pf:.2f}")
        self.stat_labels["Sharpe"].setText(f"{adv['sharpe']:.2f}")
        self.stat_labels["Racha Ganadora"].setText(str(adv["max_win_streak"]))
        self.stat_labels["Racha Perdedora"].setText(str(adv["max_loss_streak"]))
        self.stat_labels["Mejor R"].setText(f"{adv['best_r']:.2f}R")
        self.stat_labels["Peor R"].setText(f"{adv['worst_r']:.2f}R")

    # ---------- sesiones ----------
    def _collect_session_state(self):
        """Captura todo el estado actual en un dict para guardar la sesión."""
        ch = self.chart
        return {
            "symbol": self.symbol_field.text().strip(),
            "tf": self.tf_combo.currentText(),
            "bars_count": len(ch.base_candles) if ch.base_candles else 0,
            "first_candle_time": ch.base_candles[0]["t"] if ch.base_candles else None,
            "last_candle_time": ch.base_candles[-1]["t"] if ch.base_candles else None,
            "source": "mt5" if self.live_source_is_mt5 else "csv",
            "reveal_index": ch.reveal_index,
            "view_start": ch.view_start,
            "view_count": ch.view_count,
            "auto_follow": ch.auto_follow,
            "drawings": ch.export_drawings() if ch.base_candles else None,
            "open_trade": ch.open_trade,
            "account_balance": self.account.balance,
            "ict_show_fvg": ch.ict_show_fvg,
            "ict_show_ob": ch.ict_show_ob,
            "ict_show_mss": ch.ict_show_mss,
            "ict_show_liquidity": ch.ict_show_liquidity,
            "ict_show_pd": ch.ict_show_pd,
            "ict_show_ote": ch.ict_show_ote,
            "ict_show_killzones": ch.ict_show_killzones,
            "ema_on": ch.ema_on,
            "ema_period": ch.ema_period,
            "ema2_on": ch.ema2_on,
            "ema2_period": ch.ema2_period,
            "chart_style": ch.chart_style,
            "tool": ch.tool,
            "rr_ratio": ch.rr_ratio,
            "price_digits": ch.price_digits,
            "lot_value": self.lot_spin.value(),
            "balance_spin_value": self.balance_spin.value(),
            # Trades de ESTE símbolo, no el total global del journal — es lo que
            # se muestra junto al nombre de la sesión en "Cargar sesión...", y
            # mostrar ahí el conteo global era engañoso (todas las sesiones
            # guardadas mostraban el mismo número sin importar el símbolo).
            "total_trades": sum(1 for t in self.trades if t.get("symbol") == self.symbol_field.text().strip()),
        }

    def _restore_session_ui_state(self, state):
        """Restaura toggles, tool, EMA, ICT, etc. después de cargar velas."""
        ch = self.chart
        ch.ict_show_fvg = state.get("ict_show_fvg", False)
        ch.ict_show_ob = state.get("ict_show_ob", False)
        ch.ict_show_mss = state.get("ict_show_mss", False)
        ch.ict_show_liquidity = state.get("ict_show_liquidity", False)
        ch.ict_show_pd = state.get("ict_show_pd", False)
        ch.ict_show_ote = state.get("ict_show_ote", False)
        ch.ict_show_killzones = state.get("ict_show_killzones", False)
        ch.ema_on = state.get("ema_on", False)
        ch.ema_period = state.get("ema_period", 20)
        ch.ema2_on = state.get("ema2_on", False)
        ch.ema2_period = state.get("ema2_period", 50)
        ch.chart_style = state.get("chart_style", "candles")
        ch.rr_ratio = state.get("rr_ratio", 2.0)
        digits = state.get("price_digits")
        ch.price_digits = digits if digits is not None else ch.price_digits

        # Sincronizar checkboxes en UI
        self.ict_fvg_chk.setChecked(ch.ict_show_fvg)
        self.ict_ob_chk.setChecked(ch.ict_show_ob)
        self.ict_mss_chk.setChecked(ch.ict_show_mss)
        self.ict_liq_chk.setChecked(ch.ict_show_liquidity)
        self.ict_pd_chk.setChecked(ch.ict_show_pd)
        self.ict_ote_chk.setChecked(ch.ict_show_ote)
        self.ict_kz_chk.setChecked(ch.ict_show_killzones)
        self.ema1_chk.setChecked(ch.ema_on)
        self.ema1_spin.setValue(ch.ema_period)
        self.ema2_chk.setChecked(ch.ema2_on)
        self.ema2_spin.setValue(ch.ema2_period)
        self.chart_style_chk.setChecked(ch.chart_style == "line")
        self.rr_ratio_spin.setValue(ch.rr_ratio)
        self.lot_spin.setValue(state.get("lot_value", 0.10))
        self.balance_spin.setValue(state.get("balance_spin_value", 10000.0))
        self.account.reset(state.get("account_balance", 10000.0))
        self.update_equity_display()

        # Restaurar tool activo
        tool = state.get("tool", "cursor")
        self.set_tool(tool)

    def on_save_session(self):
        if not self.chart.base_candles:
            QMessageBox.information(self, "Sin datos", "No hay ninguna sesión activa para guardar.")
            return
        name, ok = QInputDialog.getText(self, "Guardar sesión", "Nombre de la sesión:")
        if not ok or not name.strip():
            return
        state = self._collect_session_state()
        import datetime as dt
        state["saved_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        path = session_store.save_session(name.strip(), state)
        QMessageBox.information(self, "Sesión guardada", f"Sesión guardada en:\n{path}")

    def on_load_session(self):
        sessions = session_store.list_sessions()
        if not sessions:
            QMessageBox.information(self, "Sin sesiones", "No hay sesiones guardadas.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Cargar sesión")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(True)
        for s in sessions:
            text = f"{s['name']}  —  {s['symbol']} {s['tf']}  ({s['trades']} trades)"
            list_widget.addItem(text)
            list_widget.item(list_widget.count() - 1).setData(Qt.UserRole, s["path"])
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)

        # Doble clic = aceptar
        list_widget.itemDoubleClicked.connect(dialog.accept)

        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        delete_btn = QPushButton("Eliminar")
        buttons.addButton(delete_btn, QDialogButtonBox.ActionRole)
        layout.addWidget(buttons)

        def on_delete():
            row = list_widget.currentRow()
            if row < 0:
                return
            path = list_widget.item(row).data(Qt.UserRole)
            if QMessageBox.question(dialog, "Confirmar", "¿Eliminar esta sesión?") == QMessageBox.Yes:
                session_store.delete_session(path)
                list_widget.takeItem(row)
                if list_widget.count() == 0:
                    dialog.reject()
        delete_btn.clicked.connect(on_delete)

        if dialog.exec() != QDialog.Accepted:
            return
        row = list_widget.currentRow()
        if row < 0:
            return
        session_path = list_widget.item(row).data(Qt.UserRole)

        try:
            state = session_store.load_session(session_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo cargar la sesión:\n{e}")
            return

        self.pause()
        self.timer.stop()
        self._disable_live_mode()

        source = state.get("source", "mt5")
        symbol = state.get("symbol", "")
        tf = state.get("tf", "M15")

        if source == "mt5":
            if not mt5_data.MT5_AVAILABLE:
                QMessageBox.warning(self, "MT5 no disponible",
                    "Esta sesión se guardó con datos de MT5, pero la librería MetaTrader5 "
                    "no está disponible en este equipo.\n\n"
                    "Abre la app en un equipo con MT5 instalado y vuelve a intentar.")
                return
            ok, err = mt5_data.connect()
            if not ok:
                retry = QMessageBox.warning(self, "MT5 no conectado",
                    f"No se pudo conectar a MT5.\n\n{err}\n\n"
                    "Asegúrate de que MT5 esté abierto y logueado, luego vuelve a intentarlo.",
                    QMessageBox.Retry | QMessageBox.Cancel)
                if retry == QMessageBox.Retry:
                    self.on_load_session()
                return
            self.mt5_status.setText("Conectado — desde sesión")
            self.symbol_combo.clear()
            self.symbol_combo.addItems(mt5_data.list_symbols())
            self.symbol_combo.setEnabled(True)
            # Sin esto, el combo quedaba mostrando cualquier símbolo (el
            # primero de la lista tras el addItems) en vez del que trae la
            # sesión -- y como on_fetch_mt5()/on_tf_combo_changed() usan
            # symbol_combo.currentText() para saber qué pedir, cambiar de
            # timeframe después de cargar una sesión pedía el símbolo
            # equivocado (o no hacía nada si el combo quedaba vacío).
            self.symbol_combo.setCurrentText(symbol)
            self.btn_fetch.setEnabled(True)
            # Igual para el combo de TF: bloqueando señales porque si el
            # texto cambia (p. ej. de "M15" a "H4") dispararía
            # on_tf_combo_changed() a mitad de esta misma carga de sesión.
            self.tf_combo.blockSignals(True)
            self.tf_combo.setCurrentText(tf)
            self.tf_combo.blockSignals(False)

            first_time = state.get("first_candle_time")
            last_time = state.get("last_candle_time")
            bars_count = state.get("bars_count", 3000)
            import datetime as dt
            # Usar SIEMPRE naive datetime (sin timezone) para compatibilidad con MT5
            if first_time and last_time:
                try:
                    t0 = dt.datetime.strptime(first_time, "%Y.%m.%d %H:%M")
                    t1 = dt.datetime.strptime(last_time, "%Y.%m.%d %H:%M")
                    margin = (t1 - t0) * 0.2 or dt.timedelta(hours=24)
                    date_from = t0 - margin
                    date_to = t1 + margin
                except ValueError:
                    date_from = dt.datetime.utcnow() - dt.timedelta(days=30)
                    date_to = dt.datetime.utcnow()
            else:
                date_from = dt.datetime.utcnow() - dt.timedelta(days=30)
                date_to = dt.datetime.utcnow()

            self._session_restore_pending = state
            self.status_label.setText("Cargando sesión…")
            self._set_data_controls_enabled(False)
            self._pending_symbol = symbol
            self._pending_tf = tf
            # Intentar primero por rango de fechas; si falla, reintentar por conteo
            self._session_fetch_mode = "range"
            self._session_bars_count = bars_count
            self._session_date_from = date_from
            self._session_date_to = date_to
            self._fetch_worker = FetchWorker("range", symbol, tf, date_from=date_from, date_to=date_to)
            self._fetch_worker.finished_ok.connect(self._on_session_fetch_ok)
            self._fetch_worker.finished_err.connect(self._on_session_fetch_err_retry)
            self._fetch_worker.start()
        else:
            QMessageBox.information(self, "Sesión CSV",
                "Esta sesión se guardó con datos de un archivo CSV.\n\n"
                "Usa '📂 CSV manual' para cargar el mismo archivo primero, "
                "luego la sesión se restaurará.")

    def _on_session_fetch_ok(self, candles):
        try:
            self._set_data_controls_enabled(True)
            state = getattr(self, "_session_restore_pending", None) or {}
            self._session_restore_pending = None

            symbol = state.get("symbol", self._pending_symbol)
            tf = state.get("tf", self._pending_tf)

            self.chart.set_candles(candles)
            self.symbol_field.setText(symbol)
            digits = state.get("price_digits")
            self.chart.price_digits = digits if digits is not None else self._get_symbol_digits(symbol)

            # Restaurar dibujos
            drawings = state.get("drawings")
            if drawings:
                self.chart.import_drawings(drawings, candles, tf_seconds=mt5_data.TF_SECONDS.get(tf, 900))

            # Restaurar posición del replay
            reveal_index = state.get("reveal_index", len(candles))
            self.chart.reveal_index = min(reveal_index, len(candles))
            self.chart.view_start = state.get("view_start", self.chart.view_start)
            self.chart.view_count = state.get("view_count", self.chart.view_count)
            self.chart.auto_follow = state.get("auto_follow", True)

            # Restaurar open trade
            self.chart.open_trade = state.get("open_trade")

            # Restaurar UI toggles
            self._restore_session_ui_state(state)

            self.live_source_is_mt5 = True

            # Si el replay estaba fijado, deshabilitar vivo
            if self.chart.is_bounded():
                self._disable_live_mode()
            else:
                self._activate_live_mode()

            self._update_live_button()
            self.chart.tf_seconds = mt5_data.TF_SECONDS.get(tf, 900)
            self.status_label.setText(f"{symbol} ({tf}) — sesión restaurada ({len(candles)} velas)")
            self._reset_controls_after_load(len(candles))
            self.refresh_open_banner()
            self.update_scrub_label()
            self.update_last_close()
            self.chart.setFocus()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._set_data_controls_enabled(True)
            self.status_label.setText("Error al restaurar sesión")
            QMessageBox.critical(self, "Error al restaurar sesión",
                f"Ocurrió un error inesperado:\n{e}\n\n{tb}")

    def _on_session_fetch_err_retry(self, err):
        """Si la carga por rango de fechas falla, reintenta por cantidad de velas."""
        mode = getattr(self, "_session_fetch_mode", "range")
        if mode == "range":
            symbol = getattr(self, "_pending_symbol", "")
            tf = getattr(self, "_pending_tf", "M15")
            bars_count = getattr(self, "_session_bars_count", 3000)
            self._session_fetch_mode = "count"
            self.status_label.setText(f"Reintentando carga ({bars_count} velas)…")
            self._fetch_worker = FetchWorker("count", symbol, tf, count=bars_count)
            self._fetch_worker.finished_ok.connect(self._on_session_fetch_ok)
            self._fetch_worker.finished_err.connect(self._on_session_fetch_err)
            self._fetch_worker.start()
        else:
            self._on_session_fetch_err(err)

    def _on_session_fetch_err(self, err):
        self._set_data_controls_enabled(True)
        self._session_restore_pending = None
        self.status_label.setText("Error al cargar sesión")
        QMessageBox.warning(self, "Error", f"No se pudieron recargar los datos:\n{err}")

    # ---------- exportar PDF ----------
    def on_export_pdf(self):
        if not self.trades:
            QMessageBox.information(self, "Sin operaciones", "No hay operaciones en el journal para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar journal a PDF", "", "PDF (*.pdf)"
        )
        if not path:
            return

        total = len(self.trades)
        wins = sum(1 for t in self.trades if t["result"] == "Ganada")
        losses = sum(1 for t in self.trades if t["result"] == "Perdida")
        winrate = (wins / total * 100) if total else 0
        sum_r = sum(t["r"] for t in self.trades)
        expectancy = (sum_r / total) if total else 0

        stats = {
            "total": total, "wins": wins, "losses": losses,
            "winrate": winrate, "sum_r": sum_r, "expectancy": expectancy,
        }
        stats.update(journal_stats.compute_advanced_stats(self.trades))

        try:
            pdf_export.build_pdf(path, self.trades, stats)
            QMessageBox.information(self, "PDF exportado",
                f"Journal exportado correctamente a:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo exportar el PDF:\n{e}")
