"""Widget de gráfico de velas: zoom, pan, crosshair, EMA, líneas horizontales y Fibonacci."""
import datetime
from PySide6.QtWidgets import QWidget, QPushButton, QMenu, QColorDialog, QLabel
from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from core.data_utils import compute_ema
from core.formatting import format_price

COL_BG = QColor("#1e222d")
COL_GRID = QColor("#242832")
COL_TEXT = QColor("#9598a1")
COL_UP = QColor("#26a69a")
COL_DOWN = QColor("#ef5350")
COL_GOLD = QColor("#c9a227")
COL_BLUE = QColor("#2962ff")
COL_CROSS = QColor("#4b4f5a")
COL_HLINE = QColor("#9598a1")

FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
FIB_COLORS = ["#787b86", "#26a69a", "#2962ff", "#c9a227", "#9c27b0", "#ef5350", "#787b86"]

PAD_L, PAD_R, PAD_T, PAD_B = 8, 66, 8, 8


class ChartWidget(QWidget):
    ohlc_hover = Signal(str)
    trade_touched = Signal(str, float, str)  # result label, exit price, exit time
    buy_clicked = Signal()
    sell_clicked = Signal()
    step_back_requested = Signal()
    play_pause_requested = Signal()
    step_requested = Signal()
    lock_requested = Signal()
    replay_locked = Signal()
    open_trade_changed = Signal()
    tool_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.base_candles = []
        self.reveal_index = 0
        self.last_hover_idx = None

        self.view_start = 0
        self.view_count = 80
        self.auto_follow = True

        self.ema_on = False
        self.ema_period = 20
        self.ema2_on = False
        self.ema2_period = 50
        self.chart_style = "candles"  # "candles" | "line"
        # Caché incremental de EMA: evita recalcular todo el histórico revelado en
        # cada repintado (ver auditoría técnica, sección de rendimiento). Se limpia
        # por completo en set_candles(); se actualiza de forma incremental cuando
        # solo se agregan velas nuevas (step() o tick en vivo).
        self._ema_cache = {}

        # Dígitos decimales reales del símbolo actual (los fija MainWindow tras
        # consultar MT5). Si es None, se usa una heurística por magnitud.
        self.price_digits = None

        self.h_lines = []
        self.fibs = []
        self.trendlines = []
        self.rects = []
        self.rr_boxes = []
        self.rr_ratio = 2.0
        self.tool = "cursor"
        self.drag_start = None
        self.drag_current = None

        self.open_trade = None
        self.crosshair = None
        self._active_drag = None

        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_start_view = 0
        self._pan_start_price_offset = 0.0
        self._price_pan_offset = 0.0  # desplazamiento vertical manual (arriba/abajo)
        self._dragging_line = None  # None | "sl" | "tp"
        self._price_scale_factor = 1.0  # zoom vertical manual, se aplica sobre el auto-ajuste
        self._axis_dragging = False
        self._axis_drag_start_y = 0
        self._axis_drag_start_factor = 1.0

        self._min = 0
        self._max = 1
        self._plot_h = 1
        self._candle_w = 10

        self.buy_btn = QPushButton("▲ BUY", self)
        self.buy_btn.setStyleSheet(
            "QPushButton { background: rgba(26,166,154,0.18); color: #26a69a; border: 1.5px solid #26a69a;"
            " border-radius: 5px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(26,166,154,0.32); }"
        )
        self.buy_btn.clicked.connect(self.buy_clicked.emit)

        self.sell_btn = QPushButton("▼ SELL", self)
        self.sell_btn.setStyleSheet(
            "QPushButton { background: rgba(239,83,80,0.18); color: #ef5350; border: 1.5px solid #ef5350;"
            " border-radius: 5px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(239,83,80,0.32); }"
        )
        self.sell_btn.clicked.connect(self.sell_clicked.emit)

        playback_style = (
            "QPushButton { background: rgba(30,34,45,0.85); color: #d1d4dc; border: 1.5px solid #2a2e39;"
            " border-radius: 5px; padding: 6px 12px; font-weight: 600; }"
            "QPushButton:hover { border-color: #8a742a; }"
        )
        self.step_back_btn = QPushButton("⏮", self)
        self.step_back_btn.setStyleSheet(playback_style)
        self.step_back_btn.clicked.connect(self.step_back_requested.emit)

        self.play_btn = QPushButton("▶", self)
        self.play_btn.setStyleSheet(playback_style)
        self.play_btn.clicked.connect(self.play_pause_requested.emit)

        self.step_btn = QPushButton("⏭", self)
        self.step_btn.setStyleSheet(playback_style)
        self.step_btn.clicked.connect(self.step_requested.emit)

        self.lock_btn = QPushButton("📍 Fijar inicio aquí", self)
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(
            "QPushButton { background: rgba(201,162,39,0.14); color: #c9a227; border: 1.5px solid #c9a227;"
            " border-radius: 5px; padding: 6px 12px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(201,162,39,0.28); }"
            "QPushButton:checked { background: rgba(201,162,39,0.4); }"
        )
        self.lock_btn.clicked.connect(self.lock_requested.emit)

        self.tf_seconds = 900  # duración de vela del timeframe actual, la fija MainWindow
        self.countdown_label = QLabel("", self)
        self.countdown_label.setStyleSheet(
            "QLabel { background: rgba(19,23,34,0.92); color: #c9a227; border: 1px solid #2a2e39;"
            " border-radius: 4px; padding: 2px 7px; font-family: ui-monospace, Consolas, monospace;"
            " font-size: 11px; font-weight: 600; }"
        )
        self.countdown_label.setVisible(False)
        self.countdown_label.adjustSize()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(1000)

        # ── ICT toggles ──
        self.ict_show_fvg = False
        self.ict_show_ob = False
        self.ict_show_mss = False
        self.ict_show_liquidity = False
        self.ict_show_pd = False
        self.ict_show_ote = False
        self.ict_show_killzones = False
        self._ict_cache = {}

        self.killzone_label = QLabel("", self)
        self.killzone_label.setStyleSheet(
            "QLabel { background: rgba(19,23,34,0.92); color: #c9a227; border: 1px solid #2a2e39;"
            " border-radius: 4px; padding: 2px 7px; font-family: ui-monospace, Consolas, monospace;"
            " font-size: 11px; font-weight: 600; }"
        )
        self.killzone_label.setVisible(False)
        self.killzone_label.adjustSize()

        self._position_overlay_buttons()

    # ---------- formateo ----------
    def _fmt_price(self, value):
        return format_price(value, self.price_digits)

    def _update_countdown(self):
        """Contador regresivo hasta que cierre la vela actual — solo tiene sentido
        con el gráfico totalmente abierto (en vivo), no durante un replay ciego."""
        if not self.isVisible():
            return
        if not self.base_candles or self.is_bounded():
            self.countdown_label.setVisible(False)
            return
        try:
            last_open = datetime.datetime.strptime(self.base_candles[-1]["t"], "%Y.%m.%d %H:%M")
        except (ValueError, IndexError):
            self.countdown_label.setVisible(False)
            return
        close_time = last_open + datetime.timedelta(seconds=self.tf_seconds)
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        remaining = (close_time - now_utc).total_seconds()
        remaining = max(0, remaining)
        hh, rem = divmod(int(remaining), 3600)
        mm, ss = divmod(rem, 60)
        text = f"⏱ {hh:02d}:{mm:02d}:{ss:02d}" if hh else f"⏱ {mm:02d}:{ss:02d}"
        self.countdown_label.setText(text)
        self.countdown_label.adjustSize()
        self.countdown_label.setVisible(True)
        self._position_countdown_label()

    def _position_countdown_label(self):
        price = self.current_close()
        y = self._y_of(price) + 24 if self._max != self._min else 40
        y = max(PAD_T, min(self.height() - 20, y))
        x = self.width() - self.countdown_label.width() - 4
        self.countdown_label.move(int(x), int(y))

    def set_playing_visual(self, playing):
        self.play_btn.setText("⏸" if playing else "▶")

    def set_lock_visual(self, active):
        self.lock_btn.setChecked(active)

    def _position_overlay_buttons(self):
        margin = 12
        bh = self.buy_btn.sizeHint().height()
        by = self.height() - bh - margin
        self.buy_btn.move(margin, by)
        self.sell_btn.move(margin + self.buy_btn.sizeHint().width() + 8, by)

        widths = [b.sizeHint().width() for b in (self.step_back_btn, self.play_btn, self.step_btn)]
        total_w = sum(widths) + 16
        start_x = (self.width() - total_w) // 2
        x = start_x
        for btn, wdt in zip((self.step_back_btn, self.play_btn, self.step_btn), widths):
            btn.move(x, by)
            x += wdt + 8

        lock_w = self.lock_btn.sizeHint().width()
        self.lock_btn.move(self.width() - lock_w - margin, by)

    def resizeEvent(self, event):
        self._position_overlay_buttons()
        if self.countdown_label.isVisible():
            self._position_countdown_label()
        if self.killzone_label.isVisible():
            self.killzone_label.move(self.width() - self.killzone_label.width() - 4, self.countdown_label.y() - 22 if self.countdown_label.isVisible() else PAD_T + 4)
        super().resizeEvent(event)

    # ---------- data ----------
    def set_candles(self, candles):
        self.base_candles = candles
        self.reveal_index = len(candles)  # todo visible/navegable por defecto, sin bloqueos
        self.view_count = min(80, len(candles))
        self.view_start = max(0, self.reveal_index - self.view_count + self._right_margin())
        self.auto_follow = True
        self.open_trade = None
        self._price_scale_factor = 1.0
        self._price_pan_offset = 0.0
        self.h_lines = []
        self.fibs = []
        self.trendlines = []
        self.rects = []
        self.rr_boxes = []
        self._ema_cache = {}
        self._ict_cache = {}
        self.update()

    def visible_base_slice(self):
        return self.base_candles[:self.reveal_index]

    def display_candles(self):
        return self.visible_base_slice()

    def is_bounded(self):
        """True si el replay ya está 'fijado' en un punto (modo ciego activo)."""
        return self.reveal_index < len(self.base_candles)

    def lock_replay_here(self, idx):
        """Fija el punto de partida del replay ciego en la vela `idx`."""
        idx = max(30, min(idx, len(self.base_candles)))
        self.reveal_index = idx
        self.open_trade = None
        self.view_count = min(80, self.reveal_index)
        self.view_start = max(0, self.reveal_index - self.view_count + self._right_margin())
        self.auto_follow = True
        self.update()

    def step(self):
        if self.reveal_index >= len(self.base_candles):
            return False
        new_candle = self.base_candles[self.reveal_index]
        self.reveal_index += 1
        if self.open_trade:
            self._check_trade_close(new_candle)
        self.update()
        return True

    def step_back(self):
        floor = self.view_count
        if self.reveal_index > floor:
            self.reveal_index -= 1
            self.update()

    def _check_trade_close(self, candle):
        """Comprueba si la vela toca el SL o el TP de la operación abierta.

        Nota de modelado: si una misma vela toca ambos niveles (posible en velas de
        alta volatilidad, p. ej. en killzones de XAUUSD), los datos OHLC no dicen
        en qué orden ocurrió realmente el movimiento intra-vela. Esta app asume,
        de forma conservadora, que el SL se ejecuta primero — es la misma
        simplificación que usan la mayoría de plataformas de backtesting basadas
        en velas, pero conviene tenerla presente al leer el winrate reportado.
        """
        t = self.open_trade
        if t["dir"] == "buy":
            hit_sl = candle["l"] <= t["sl"]
            hit_tp = candle["h"] >= t["tp"]
        else:
            hit_sl = candle["h"] >= t["sl"]
            hit_tp = candle["l"] <= t["tp"]
        if hit_sl or hit_tp:
            exit_price = t["sl"] if hit_sl else t["tp"]
            result = "Perdida" if hit_sl else "Ganada"
            self.trade_touched.emit(result, exit_price, candle["t"])

    def current_close(self):
        idx = min(self.reveal_index, len(self.base_candles)) - 1
        if idx < 0 or not self.base_candles:
            return 0.0
        return self.base_candles[idx]["c"]

    def default_stop_distance(self):
        """Distancia por defecto para el SL/TP recién ejecutado — un porcentaje del
        precio actual, para que las líneas aparezcan visibles y las puedas arrastrar
        de inmediato, como al abrir una orden a mercado en MT5."""
        price = self.current_close()
        return max(price * 0.003, 0.00001)

    # ---------- EMA (con caché incremental) ----------
    def _get_ema(self, period):
        """Devuelve la EMA del período dado, recalculando solo lo estrictamente
        necesario en vez de todo el histórico revelado en cada frame:
        - primera vez / el histórico se acortó (nuevo símbolo, replay recién
          fijado en un punto anterior): recálculo completo.
        - misma cantidad de velas pero la última cambió de close (tick en vivo):
          solo se recalcula el último valor.
        - se agregaron velas nuevas (step() o vela nueva en vivo): se extiende el
          array existente vela por vela, sin tocar lo ya calculado.
        """
        candles = self.display_candles()
        n = len(candles)
        cache = self._ema_cache.get(period)
        last_t = candles[-1]["t"] if candles else None

        if cache is None or n < cache["n"]:
            values = compute_ema(candles, period)
            self._ema_cache[period] = {"n": n, "last_t": last_t, "values": values}
            return values

        if n == cache["n"]:
            if last_t != cache["last_t"] and n > 0:
                # Mismo total de velas, pero cambió el timestamp final: algo se
                # reemplazó por completo (no debería pasar en uso normal, pero
                # por seguridad recalculamos entero en vez de arrastrar un caché
                # desalineado).
                values = compute_ema(candles, period)
                cache.update({"n": n, "last_t": last_t, "values": values})
                return values
            if n >= period:
                # Tick en vivo: el precio de cierre de la última vela cambió.
                k = 2 / (period + 1)
                prev = cache["values"][n - 2] if n >= 2 else None
                if prev is not None:
                    cache["values"][n - 1] = candles[-1]["c"] * k + prev * (1 - k)
                elif n == period:
                    cache["values"][n - 1] = sum(c["c"] for c in candles[:period]) / period
            return cache["values"]

        # n > cache["n"]: velas nuevas al final — extensión incremental.
        values = cache["values"]
        k = 2 / (period + 1)
        for i in range(cache["n"], n):
            if i < period - 1:
                values.append(None)
            elif i == period - 1:
                values.append(sum(c["c"] for c in candles[:period]) / period)
            else:
                prev = values[i - 1]
                values.append(candles[i]["c"] * k + prev * (1 - k) if prev is not None else None)
        cache["n"] = n
        cache["last_t"] = last_t
        return values

    # ---------- coordinate mapping ----------
    def _right_margin(self):
        """Espacio vacío (en velas) que se deja a la derecha para que el precio no quede pegado al borde."""
        return max(8, int(self.view_count * 0.25))

    def _max_view_start(self, num_candles):
        return max(0, num_candles - self.view_count + self._right_margin())

    def _y_of(self, v):
        return PAD_T + self._plot_h - ((v - self._min) / (self._max - self._min)) * self._plot_h

    def _price_from_y(self, y):
        return self._max - ((y - PAD_T) / self._plot_h) * (self._max - self._min)

    def _x_of(self, idx, view_start, candle_w):
        return PAD_L + (idx - view_start) * candle_w + candle_w / 2

    def _idx_from_x(self, x, view_start, candle_w):
        return view_start + int((x - PAD_L) / candle_w) if candle_w else 0

    # ---------- painting ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, COL_BG)

        candles = self.display_candles()
        if not candles:
            # Sin datos: dejamos min/max en un rango seguro para que cualquier
            # manejador de mouse que se dispare antes de la próxima carga no opere
            # sobre un rango de precio obsoleto de una carga anterior.
            self._min, self._max = 0, 1
            p.end()
            return

        self.view_count = max(15, min(self.view_count, len(candles)))
        if self.auto_follow:
            self.view_start = self._max_view_start(len(candles))
        self.view_start = max(0, min(self.view_start, self._max_view_start(len(candles))))

        visible = candles[self.view_start:self.view_start + self.view_count]
        if not visible:
            self._min, self._max = 0, 1
            p.end()
            return

        vmin = min(c["l"] for c in visible)
        vmax = max(c["h"] for c in visible)
        if self.open_trade:
            vmin = min(vmin, self.open_trade["sl"], self.open_trade["tp"])
            vmax = max(vmax, self.open_trade["sl"], self.open_trade["tp"])
        # Los dibujos (líneas, tendencias, rectángulos, fibs, cajas R:R) NO deben
        # estirar el rango automático — si uno queda con un precio muy lejano,
        # simplemente se dibuja fuera de la vista en vez de aplastar las velas.
        pad = (vmax - vmin) * 0.08 or vmax * 0.001 or 1
        vmin -= pad; vmax += pad
        center = (vmin + vmax) / 2 + self._price_pan_offset
        half = (vmax - vmin) / 2 * self._price_scale_factor
        vmin, vmax = center - half, center + half
        self._min, self._max = vmin, vmax

        plot_w = w - PAD_L - PAD_R
        self._plot_h = h - PAD_T - PAD_B
        self._candle_w = plot_w / self.view_count
        candle_w = self._candle_w

        # grid
        font = QFont("monospace", 8)
        p.setFont(font)
        pen_grid = QPen(COL_GRID); pen_grid.setWidth(1)
        p.setPen(pen_grid)
        for i in range(6):
            v = vmin + (vmax - vmin) * i / 5
            y = self._y_of(v)
            p.drawLine(PAD_L, int(y), w - PAD_R, int(y))
            p.setPen(COL_TEXT)
            p.drawText(int(w - PAD_R + 6), int(y + 3), self._fmt_price(v))
            p.setPen(pen_grid)

        # candles / línea de precio de cierre
        if self.chart_style == "line":
            pts = []
            for i, c in enumerate(visible):
                idx = self.view_start + i
                x = self._x_of(idx, self.view_start, candle_w)
                pts.append(QPointF(x, self._y_of(c["c"])))
            p.setPen(QPen(COL_BLUE, 2))
            for j in range(1, len(pts)):
                p.drawLine(pts[j - 1], pts[j])
        else:
            for i, c in enumerate(visible):
                idx = self.view_start + i
                x = self._x_of(idx, self.view_start, candle_w)
                up = c["c"] >= c["o"]
                color = COL_UP if up else COL_DOWN
                p.setPen(QPen(color, 1))
                p.drawLine(int(x), int(self._y_of(c["h"])), int(x), int(self._y_of(c["l"])))
                body_top = self._y_of(max(c["o"], c["c"]))
                body_bot = self._y_of(min(c["o"], c["c"]))
                bw = max(candle_w * 0.62, 1)
                p.fillRect(int(x - bw / 2), int(body_top), int(bw), max(int(body_bot - body_top), 1), color)

        # EMAs
        def draw_ema(period, color):
            ema = self._get_ema(period)
            pen = QPen(QColor(color), 2)
            p.setPen(pen)
            pts = []
            for i in range(self.view_start, min(self.view_start + self.view_count, len(ema))):
                v = ema[i]
                if v is None:
                    continue
                pts.append(QPointF(self._x_of(i, self.view_start, candle_w), self._y_of(v)))
            for j in range(1, len(pts)):
                p.drawLine(pts[j - 1], pts[j])

        if self.ema_on:
            draw_ema(self.ema_period, "#c9a227")
        if self.ema2_on:
            draw_ema(self.ema2_period, "#2962ff")

        # ── ICT Drawings ──
        ict = self._get_ict_cache()
        if ict:
            if self.ict_show_pd and ict.get("pd_array"):
                self._draw_pd_array(p, ict["pd_array"], w)
            if self.ict_show_fvg and ict.get("fvgs"):
                self._draw_fvgs(p, ict["fvgs"])
            if self.ict_show_ob:
                if ict.get("swing_order_blocks"):
                    self._draw_order_blocks(p, ict["swing_order_blocks"], internal=False)
                if ict.get("internal_order_blocks"):
                    self._draw_order_blocks(p, ict["internal_order_blocks"], internal=True)
            if self.ict_show_mss:
                if ict.get("swing_structure"):
                    self._draw_structure(p, ict["swing_structure"], internal=False)
                if ict.get("internal_structure"):
                    self._draw_structure(p, ict["internal_structure"], internal=True)
            if self.ict_show_liquidity and (ict.get("equal_highs") or ict.get("equal_lows")):
                self._draw_equal_highs_lows(p, ict.get("equal_highs", []), ict.get("equal_lows", []), w)
            if self.ict_show_ote and ict.get("ote"):
                self._draw_ote(p, ict["ote"])
            if self.ict_show_killzones:
                self._draw_killzones(p, w)

        # open trade lines
        if self.open_trade:
            t = self.open_trade
            for val, color, label in [
                (t["entry"], "#c9a227", f"Entrada {self._fmt_price(t['entry'])}"),
                (t["sl"], "#ef5350", f"SL {self._fmt_price(t['sl'])}"),
                (t["tp"], "#26a69a", f"TP {self._fmt_price(t['tp'])}"),
            ]:
                y = self._y_of(val)
                pen = QPen(QColor(color), 1, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(PAD_L, int(y), w - PAD_R, int(y))
                p.setPen(QColor(color))
                p.drawText(PAD_L + 4, int(y - 3), label)

        # horizontal lines
        for ln in self.h_lines:
            price = ln["price"] if isinstance(ln, dict) else ln
            color = ln.get("color", "#9598a1") if isinstance(ln, dict) else "#9598a1"
            width = ln.get("width", 1) if isinstance(ln, dict) else 1
            y = self._y_of(price)
            pen = QPen(QColor(color), width, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(PAD_L, int(y), w - PAD_R, int(y))
            p.setPen(QColor(color))
            p.drawText(int(w - PAD_R + 6), int(y + 3), self._fmt_price(price))

        # tendencias
        for l in self.trendlines:
            x1, y1 = self._x_of(l["i1"], self.view_start, candle_w), self._y_of(l["p1"])
            x2, y2 = self._x_of(l["i2"], self.view_start, candle_w), self._y_of(l["p2"])
            pen = QPen(QColor(l.get("color", "#e0a800")), l.get("width", 2))
            p.setPen(pen)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        # rectángulos (para marcar zonas: FVG, order blocks, killzones...)
        for r in self.rects:
            x_l = min(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            y_t = min(self._y_of(r["p1"]), self._y_of(r["p2"]))
            y_b = max(self._y_of(r["p1"]), self._y_of(r["p2"]))
            rc = r.get("color", "#c9a227")
            fill = QColor(rc); fill.setAlpha(35)
            p.fillRect(int(x_l), int(y_t), int(x_r - x_l), int(y_b - y_t), fill)
            pen = QPen(QColor(rc), r.get("width", 1))
            p.setPen(pen)
            p.drawRect(int(x_l), int(y_t), int(x_r - x_l), int(y_b - y_t))

        # cajas de riesgo/beneficio (long y short)
        for box in self.rr_boxes:
            x_l = min(self._x_of(box["i1"], self.view_start, candle_w), self._x_of(box["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(box["i1"], self.view_start, candle_w), self._x_of(box["i2"], self.view_start, candle_w))
            entry, sl, tp = box["entry"], box["sl"], box["tp"]
            y_entry, y_sl, y_tp = self._y_of(entry), self._y_of(sl), self._y_of(tp)
            green = QColor("#26a69a"); green.setAlpha(45)
            red = QColor("#ef5350"); red.setAlpha(45)
            top_profit, bot_profit = (y_tp, y_entry) if y_tp < y_entry else (y_entry, y_tp)
            top_loss, bot_loss = (y_entry, y_sl) if y_entry < y_sl else (y_sl, y_entry)
            p.fillRect(int(x_l), int(top_profit), int(x_r - x_l), int(bot_profit - top_profit), green)
            p.fillRect(int(x_l), int(top_loss), int(x_r - x_l), int(bot_loss - top_loss), red)
            pen = QPen(QColor("#c9a227"), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(int(x_l), int(y_entry), int(x_r), int(y_entry))
            p.setPen(QColor("#d1d4dc"))
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr_txt = f"{box['kind'].upper()}  Riesgo: {self._fmt_price(risk)}  Beneficio: {self._fmt_price(reward)}  R:R 1:{box['ratio']:.1f}"
            p.drawText(int(x_l) + 4, int(top_profit) - 4 if box["kind"] == "long" else int(bot_loss) + 14, rr_txt)

        # fibonacci
        for f in self.fibs:
            x_l = min(self._x_of(f["i1"], self.view_start, candle_w), self._x_of(f["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(f["i1"], self.view_start, candle_w), self._x_of(f["i2"], self.view_start, candle_w))
            rng = f["p2"] - f["p1"]
            for lvl, color in zip(FIB_LEVELS, FIB_COLORS):
                price = f["p1"] + rng * lvl
                y = self._y_of(price)
                pen = QPen(QColor(color), 1, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(int(x_l), int(y), int(x_r), int(y))
                p.setPen(QColor(color))
                p.drawText(int(x_r + 4), int(y + 3), f"{lvl:.3f} — {self._fmt_price(price)}")

        # línea de precio actual (persistente, como en MT5 — no depende del mouse)
        last_price = self.current_close()
        if last_price and self._min <= last_price <= self._max:
            py = self._y_of(last_price)
            pen = QPen(COL_BLUE, 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(PAD_L, int(py), w - PAD_R, int(py))
            label = self._fmt_price(last_price)
            p.fillRect(w - PAD_R, int(py - 8), PAD_R, 16, COL_BLUE)
            p.setPen(QColor("#ffffff"))
            p.drawText(w - PAD_R + 4, int(py + 4), label)

        # drag preview
        TWO_CLICK_TOOLS = ("fib", "trend", "rect", "rr_long", "rr_short")
        if self.drag_start and self.drag_current and self.tool in TWO_CLICK_TOOLS:
            pen = QPen(COL_GOLD, 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(self.drag_start, self.drag_current)

        # crosshair
        if self.crosshair:
            cx, cy = self.crosshair.x(), self.crosshair.y()
            if self.tool == "lock":
                pen = QPen(COL_GOLD, 2, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(int(cx), PAD_T, int(cx), h - PAD_B)
                p.setPen(COL_GOLD)
                p.drawText(int(cx) + 6, PAD_T + 14, "clic para fijar el inicio aquí")
            else:
                pen = QPen(COL_CROSS, 1, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(int(cx), PAD_T, int(cx), h - PAD_B)
                p.drawLine(PAD_L, int(cy), w - PAD_R, int(cy))

        p.end()

    # ---------- mouse ----------
    def _hit_test_handles(self, pos):
        """Detecta si el punto cae sobre un borde/extremo/cuerpo de un dibujo, para
        poder redimensionarlo o moverlo arrastrando (clic izquierdo, modo Cursor)."""
        x, y = pos.x(), pos.y()
        candle_w = self._candle_w or 10
        threshold = 8

        for i, ln in enumerate(self.h_lines):
            price = ln["price"] if isinstance(ln, dict) else ln
            if abs(self._y_of(price) - y) <= threshold:
                return {"kind": "hline", "idx": i, "handle": "move"}

        for i, l in enumerate(self.trendlines):
            x1, y1 = self._x_of(l["i1"], self.view_start, candle_w), self._y_of(l["p1"])
            x2, y2 = self._x_of(l["i2"], self.view_start, candle_w), self._y_of(l["p2"])
            if abs(x - x1) <= threshold and abs(y - y1) <= threshold:
                return {"kind": "trend", "idx": i, "handle": "p1"}
            if abs(x - x2) <= threshold and abs(y - y2) <= threshold:
                return {"kind": "trend", "idx": i, "handle": "p2"}
            if self._dist_point_to_segment(x, y, x1, y1, x2, y2) <= threshold:
                return {"kind": "trend", "idx": i, "handle": "move"}

        for i, r in enumerate(self.rects):
            x_l = min(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            y_t = min(self._y_of(r["p1"]), self._y_of(r["p2"]))
            y_b = max(self._y_of(r["p1"]), self._y_of(r["p2"]))
            if abs(x - x_l) <= threshold and y_t - threshold <= y <= y_b + threshold:
                return {"kind": "rect", "idx": i, "handle": "left"}
            if abs(x - x_r) <= threshold and y_t - threshold <= y <= y_b + threshold:
                return {"kind": "rect", "idx": i, "handle": "right"}
            if abs(y - y_t) <= threshold and x_l - threshold <= x <= x_r + threshold:
                return {"kind": "rect", "idx": i, "handle": "top"}
            if abs(y - y_b) <= threshold and x_l - threshold <= x <= x_r + threshold:
                return {"kind": "rect", "idx": i, "handle": "bottom"}
            if x_l <= x <= x_r and y_t <= y <= y_b:
                return {"kind": "rect", "idx": i, "handle": "move"}

        for i, b in enumerate(self.rr_boxes):
            x_l = min(self._x_of(b["i1"], self.view_start, candle_w), self._x_of(b["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(b["i1"], self.view_start, candle_w), self._x_of(b["i2"], self.view_start, candle_w))
            y_entry, y_sl, y_tp = self._y_of(b["entry"]), self._y_of(b["sl"]), self._y_of(b["tp"])
            y_top = min(y_sl, y_tp)
            y_bot = max(y_sl, y_tp)
            if not (x_l - threshold <= x <= x_r + threshold):
                continue
            if abs(y - y_entry) <= threshold:
                return {"kind": "rr_box", "idx": i, "handle": "entry"}
            if abs(y - y_sl) <= threshold:
                return {"kind": "rr_box", "idx": i, "handle": "sl"}
            if abs(y - y_tp) <= threshold:
                return {"kind": "rr_box", "idx": i, "handle": "tp"}
            if abs(x - x_l) <= threshold and y_top - threshold <= y <= y_bot + threshold:
                return {"kind": "rr_box", "idx": i, "handle": "left"}
            if abs(x - x_r) <= threshold and y_top - threshold <= y <= y_bot + threshold:
                return {"kind": "rr_box", "idx": i, "handle": "right"}
            if x_l <= x <= x_r and y_top <= y <= y_bot:
                return {"kind": "rr_box", "idx": i, "handle": "move"}
        return None

    def _apply_drag(self, pos):
        d = self._active_drag
        kind, idx, handle, orig = d["kind"], d["idx"], d["handle"], d["orig"]
        candle_w = self._candle_w or 10
        new_price = self._price_from_y(pos.y())
        new_idx = self._idx_from_x(pos.x(), self.view_start, candle_w)
        obj = getattr(self, self._KIND_LISTS[kind])[idx]

        if kind == "hline":
            obj["price"] = new_price
        elif kind == "trend":
            if handle == "p1":
                obj["p1"], obj["i1"] = new_price, new_idx
            elif handle == "p2":
                obj["p2"], obj["i2"] = new_price, new_idx
            elif handle == "move":
                dx_idx = new_idx - self._idx_from_x(d["start_pos"].x(), self.view_start, candle_w)
                dy_price = new_price - self._price_from_y(d["start_pos"].y())
                obj["i1"], obj["i2"] = orig["i1"] + dx_idx, orig["i2"] + dx_idx
                obj["p1"], obj["p2"] = orig["p1"] + dy_price, orig["p2"] + dy_price
        elif kind == "rect":
            top_key = "p1" if orig["p1"] >= orig["p2"] else "p2"
            bot_key = "p2" if top_key == "p1" else "p1"
            left_key = "i1" if orig["i1"] <= orig["i2"] else "i2"
            right_key = "i2" if left_key == "i1" else "i1"
            if handle == "top":
                obj[top_key] = new_price
            elif handle == "bottom":
                obj[bot_key] = new_price
            elif handle == "left":
                obj[left_key] = new_idx
            elif handle == "right":
                obj[right_key] = new_idx
            elif handle == "move":
                dx_idx = new_idx - self._idx_from_x(d["start_pos"].x(), self.view_start, candle_w)
                dy_price = new_price - self._price_from_y(d["start_pos"].y())
                obj["i1"], obj["i2"] = orig["i1"] + dx_idx, orig["i2"] + dx_idx
                obj["p1"], obj["p2"] = orig["p1"] + dy_price, orig["p2"] + dy_price
        elif kind == "rr_box":
            left_key = "i1" if orig["i1"] <= orig["i2"] else "i2"
            right_key = "i2" if left_key == "i1" else "i1"
            if handle == "entry":
                delta = new_price - orig["entry"]
                obj["entry"] = new_price
                obj["sl"] = orig["sl"] + delta
                obj["tp"] = orig["tp"] + delta
            elif handle == "sl":
                obj["sl"] = new_price
                risk = abs(obj["entry"] - obj["sl"]) or 1e-9
                reward = abs(obj["tp"] - obj["entry"])
                obj["ratio"] = reward / risk
            elif handle == "tp":
                obj["tp"] = new_price
                risk = abs(obj["entry"] - obj["sl"]) or 1e-9
                reward = abs(obj["tp"] - obj["entry"])
                obj["ratio"] = reward / risk
            elif handle == "left":
                obj[left_key] = new_idx
            elif handle == "right":
                obj[right_key] = new_idx
            elif handle == "move":
                dx_idx = new_idx - self._idx_from_x(d["start_pos"].x(), self.view_start, candle_w)
                dy_price = new_price - self._price_from_y(d["start_pos"].y())
                obj["i1"], obj["i2"] = orig["i1"] + dx_idx, orig["i2"] + dx_idx
                obj["entry"] = orig["entry"] + dy_price
                obj["sl"] = orig["sl"] + dy_price
                obj["tp"] = orig["tp"] + dy_price
        self.update()

    def _line_hit_test(self, y):
        """Devuelve 'sl' o 'tp' si `y` cae cerca de esa línea del trade abierto."""
        if not self.open_trade or self._plot_h <= 1:
            return None
        threshold = 7
        for key in ("sl", "tp"):
            val = self.open_trade.get(key)
            if val is None:
                continue
            if abs(self._y_of(val) - y) <= threshold:
                return key
        return None

    def mouseMoveEvent(self, event):
        pos = event.position()
        self.crosshair = pos

        if self._axis_dragging:
            delta = pos.y() - self._axis_drag_start_y
            factor = self._axis_drag_start_factor * (2 ** (delta / 200.0))
            self._price_scale_factor = max(0.05, min(20, factor))
            self.update()
            return

        if pos.x() >= self.width() - PAD_R and not self._active_drag and not self._dragging_line:
            self.setCursor(Qt.SizeVerCursor)
            self.crosshair = None
            self.ohlc_hover.emit("")
            self.update()
            return

        candles = self.display_candles()
        candle_w = self._candle_w or 10
        idx = self._idx_from_x(pos.x(), self.view_start, candle_w)

        if self.drag_start and self.tool in ("fib", "trend", "rect", "rr_long", "rr_short"):
            self.drag_current = pos

        if self._dragging_line:
            new_price = self._price_from_y(pos.y())
            self.open_trade[self._dragging_line] = new_price
            self.open_trade_changed.emit()
            self.update()
            return

        if self._active_drag:
            self._apply_drag(pos)
            return

        if self.tool == "cursor" and not self._is_panning:
            hit = self._line_hit_test(pos.y())
            if hit:
                self.setCursor(Qt.SizeVerCursor)
            else:
                handle = self._hit_test_handles(pos)
                shift_held = bool(event.modifiers() & Qt.ShiftModifier)
                if handle and handle["handle"] == "move" and handle["kind"] != "hline" and not shift_held:
                    handle = None
                cursor_map = {
                    "move": Qt.SizeAllCursor, "left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor,
                    "top": Qt.SizeVerCursor, "bottom": Qt.SizeVerCursor,
                    "p1": Qt.SizeAllCursor, "p2": Qt.SizeAllCursor,
                    "entry": Qt.SizeVerCursor, "sl": Qt.SizeVerCursor, "tp": Qt.SizeVerCursor,
                }
                self.setCursor(cursor_map.get(handle["handle"], Qt.ArrowCursor) if handle else Qt.ArrowCursor)

        if self._is_panning and self.tool == "cursor":
            dx = pos.x() - self._pan_start_x
            shift = int(round(-dx / candle_w))
            self.auto_follow = False
            max_start = self._max_view_start(len(candles))
            self.view_start = max(0, min(self._pan_start_view + shift, max_start))

            dy = pos.y() - self._pan_start_y
            if self._plot_h > 0:
                price_per_px = (self._max - self._min) / self._plot_h
                self._price_pan_offset = self._pan_start_price_offset + dy * price_per_px

        if 0 <= idx < len(candles):
            c = candles[idx]
            self.last_hover_idx = idx
            self.ohlc_hover.emit(
                f"{c['t']}   O:{self._fmt_price(c['o'])} H:{self._fmt_price(c['h'])} "
                f"L:{self._fmt_price(c['l'])} C:{self._fmt_price(c['c'])}"
            )
        else:
            self.ohlc_hover.emit("")
        self.update()

    def leaveEvent(self, event):
        self.crosshair = None
        self.ohlc_hover.emit("")
        self.update()

    def _finish_two_click_tool(self):
        """Vuelve al cursor normal apenas se termina de dibujar — así el próximo
        clic siempre mueve el gráfico en vez de intentar dibujar otra figura."""
        self.tool = "cursor"
        self.setCursor(Qt.ArrowCursor)
        self.tool_changed.emit("cursor")

    def mousePressEvent(self, event):
        pos = event.position()
        if pos.x() >= self.width() - PAD_R:
            self._axis_dragging = True
            self._axis_drag_start_y = pos.y()
            self._axis_drag_start_factor = self._price_scale_factor
            return
        if self.tool == "cursor":
            hit = self._line_hit_test(pos.y())
            if hit:
                self._dragging_line = hit
                return
            handle = self._hit_test_handles(pos)
            shift_held = bool(event.modifiers() & Qt.ShiftModifier)
            if handle and handle["handle"] == "move" and handle["kind"] != "hline" and not shift_held:
                handle = None
            if handle:
                obj = getattr(self, self._KIND_LISTS[handle["kind"]])[handle["idx"]]
                handle["orig"] = dict(obj)
                handle["start_pos"] = pos
                self._active_drag = handle
                return
        if self.tool == "lock":
            candle_w = self._candle_w or 10
            idx = self._idx_from_x(pos.x(), self.view_start, candle_w)
            self.lock_replay_here(idx)
            self.tool = "cursor"
            self.setCursor(Qt.ArrowCursor)
            self.replay_locked.emit()
            self.update()
            return
        if self.tool == "line":
            self.h_lines.append({"price": self._price_from_y(pos.y()), "color": "#9598a1", "width": 1})
            self._finish_two_click_tool()
            self.update()
            return
        if self.tool == "fib":
            candle_w = self._candle_w or 10
            if self.drag_start is None:
                self.drag_start = pos
            else:
                i1 = self._idx_from_x(self.drag_start.x(), self.view_start, candle_w)
                i2 = self._idx_from_x(pos.x(), self.view_start, candle_w)
                p1 = self._price_from_y(self.drag_start.y())
                p2 = self._price_from_y(pos.y())
                self.fibs.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2})
                self.drag_start = None
                self.drag_current = None
                self._finish_two_click_tool()
            self.update()
            return
        if self.tool == "trend":
            candle_w = self._candle_w or 10
            if self.drag_start is None:
                self.drag_start = pos
            else:
                i1 = self._idx_from_x(self.drag_start.x(), self.view_start, candle_w)
                i2 = self._idx_from_x(pos.x(), self.view_start, candle_w)
                p1 = self._price_from_y(self.drag_start.y())
                p2 = self._price_from_y(pos.y())
                self.trendlines.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2, "color": "#e0a800", "width": 2})
                self.drag_start = None
                self.drag_current = None
                self._finish_two_click_tool()
            self.update()
            return
        if self.tool == "rect":
            candle_w = self._candle_w or 10
            if self.drag_start is None:
                self.drag_start = pos
            else:
                i1 = self._idx_from_x(self.drag_start.x(), self.view_start, candle_w)
                i2 = self._idx_from_x(pos.x(), self.view_start, candle_w)
                p1 = self._price_from_y(self.drag_start.y())
                p2 = self._price_from_y(pos.y())
                self.rects.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2, "color": "#c9a227", "width": 1})
                self.drag_start = None
                self.drag_current = None
                self._finish_two_click_tool()
            self.update()
            return
        if self.tool in ("rr_long", "rr_short"):
            candle_w = self._candle_w or 10
            if self.drag_start is None:
                self.drag_start = pos
            else:
                kind = "long" if self.tool == "rr_long" else "short"
                i1 = self._idx_from_x(self.drag_start.x(), self.view_start, candle_w)
                i2 = self._idx_from_x(pos.x(), self.view_start, candle_w)
                entry = self._price_from_y(self.drag_start.y())
                stop_click = self._price_from_y(pos.y())
                risk = abs(entry - stop_click) or (entry * 0.003)
                if kind == "long":
                    sl = entry - risk
                    tp = entry + risk * self.rr_ratio
                else:
                    sl = entry + risk
                    tp = entry - risk * self.rr_ratio
                self.rr_boxes.append({
                    "kind": kind, "i1": i1, "i2": i2, "entry": entry, "sl": sl, "tp": tp,
                    "ratio": self.rr_ratio,
                })
                self.drag_start = None
                self.drag_current = None
                self._finish_two_click_tool()
            self.update()
            return
        self._is_panning = True
        self._pan_start_x = pos.x()
        self._pan_start_y = pos.y()
        self._pan_start_view = self.view_start
        self._pan_start_price_offset = self._price_pan_offset

    def mouseReleaseEvent(self, event):
        self._is_panning = False
        self._dragging_line = None
        self._active_drag = None
        self._axis_dragging = False

    def mouseDoubleClickEvent(self, event):
        self._price_scale_factor = 1.0
        self._price_pan_offset = 0.0
        self.update()

    def wheelEvent(self, event):
        pos = event.position()
        delta = event.angleDelta().y()
        factor = 0.87 if delta > 0 else 1.15
        if pos.x() >= self.width() - PAD_R:
            self._price_scale_factor = max(0.05, min(20, self._price_scale_factor * factor))
            self.update()
            return
        self.auto_follow = False
        candles = self.display_candles()
        new_count = int(round(max(20, min(5000, self.view_count * factor))))
        center = self.view_start + self.view_count / 2
        self.view_count = min(new_count, len(candles)) if candles else new_count
        max_start = self._max_view_start(len(candles))
        self.view_start = max(0, min(int(round(center - self.view_count / 2)), max_start))
        self.update()

    # ---------- edición de dibujos (clic derecho) ----------
    def _dist_point_to_segment(self, px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        cx, cy = x1 + t * dx, y1 + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _find_drawing_at(self, pos):
        """Busca el dibujo más cercano al punto `pos` (para editar con clic derecho).
        Cubre líneas horizontales, tendencias y rectángulos; Fibonacci y cajas R:R
        se editan hoy solo borrando todos los dibujos (roadmap: extender aquí)."""
        x, y = pos.x(), pos.y()
        candle_w = self._candle_w or 10
        threshold = 8

        for i, ln in enumerate(self.h_lines):
            price = ln["price"] if isinstance(ln, dict) else ln
            if abs(self._y_of(price) - y) <= threshold:
                return ("hline", i)

        for i, l in enumerate(self.trendlines):
            x1, y1 = self._x_of(l["i1"], self.view_start, candle_w), self._y_of(l["p1"])
            x2, y2 = self._x_of(l["i2"], self.view_start, candle_w), self._y_of(l["p2"])
            if self._dist_point_to_segment(x, y, x1, y1, x2, y2) <= threshold:
                return ("trend", i)

        for i, r in enumerate(self.rects):
            x_l = min(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            x_r = max(self._x_of(r["i1"], self.view_start, candle_w), self._x_of(r["i2"], self.view_start, candle_w))
            y_t = min(self._y_of(r["p1"]), self._y_of(r["p2"]))
            y_b = max(self._y_of(r["p1"]), self._y_of(r["p2"]))
            near_left = abs(x - x_l) <= threshold and y_t - threshold <= y <= y_b + threshold
            near_right = abs(x - x_r) <= threshold and y_t - threshold <= y <= y_b + threshold
            near_top = abs(y - y_t) <= threshold and x_l - threshold <= x <= x_r + threshold
            near_bot = abs(y - y_b) <= threshold and x_l - threshold <= x <= x_r + threshold
            if near_left or near_right or near_top or near_bot:
                return ("rect", i)

        return None

    _KIND_LISTS = {"hline": "h_lines", "trend": "trendlines", "rect": "rects", "rr_box": "rr_boxes"}
    _KIND_LABELS = {"hline": "línea horizontal", "trend": "línea de tendencia", "rect": "rectángulo", "rr_box": "caja R:R"}

    def contextMenuEvent(self, event):
        pos = event.pos()
        hit = self._find_drawing_at(pos)
        if not hit:
            return
        kind, idx = hit
        obj_list = getattr(self, self._KIND_LISTS[kind])
        obj = obj_list[idx]

        menu = QMenu(self)
        menu.addAction(f"Editar {self._KIND_LABELS[kind]}").setEnabled(False)
        menu.addSeparator()
        color_action = menu.addAction("🎨 Cambiar color…")
        width_menu = menu.addMenu("Grosor")
        width_actions = {}
        for wpx in (1, 2, 3, 4, 6):
            a = width_menu.addAction(f"{wpx}px")
            width_actions[a] = wpx
        menu.addSeparator()
        delete_action = menu.addAction("🗑 Eliminar")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen == color_action:
            current = QColor(obj.get("color", "#c9a227"))
            color = QColorDialog.getColor(current, self, "Elegir color")
            if color.isValid():
                obj["color"] = color.name()
                self.update()
        elif chosen in width_actions:
            obj["width"] = width_actions[chosen]
            self.update()
        elif chosen == delete_action:
            del obj_list[idx]
            self.update()

    # ---------- guardar/restaurar dibujos al cambiar de timeframe ----------
    def export_drawings(self):
        def idx_to_time(i):
            if not self.base_candles:
                return None
            i = max(0, min(int(i), len(self.base_candles) - 1))
            return self.base_candles[i]["t"]

        return {
            "h_lines": [dict(h) for h in self.h_lines],
            "trendlines": [
                {"t1": idx_to_time(t["i1"]), "p1": t["p1"], "t2": idx_to_time(t["i2"]), "p2": t["p2"],
                 "color": t.get("color", "#e0a800"), "width": t.get("width", 2)}
                for t in self.trendlines
            ],
            "rects": [
                {"t1": idx_to_time(r["i1"]), "p1": r["p1"], "t2": idx_to_time(r["i2"]), "p2": r["p2"],
                 "color": r.get("color", "#c9a227"), "width": r.get("width", 1)}
                for r in self.rects
            ],
            "fibs": [
                {"t1": idx_to_time(f["i1"]), "p1": f["p1"], "t2": idx_to_time(f["i2"]), "p2": f["p2"]}
                for f in self.fibs
            ],
            "rr_boxes": [
                {"t1": idx_to_time(b["i1"]), "t2": idx_to_time(b["i2"]), "entry": b["entry"],
                 "sl": b["sl"], "tp": b["tp"], "kind": b["kind"], "ratio": b["ratio"]}
                for b in self.rr_boxes
            ],
        }

    def import_drawings(self, data, new_candles, tf_seconds=900):
        def parse_dt(t):
            try:
                return datetime.datetime.strptime(t, "%Y.%m.%d %H:%M")
            except (ValueError, TypeError):
                return None

        def time_to_idx(t):
            if t is None or not new_candles:
                return 0

            # Anterior a la primera vela descargada (el rango recargado no
            # llega tan atrás como donde estaba el dibujo -- p. ej. el
            # histórico del bróker no alcanza, o el fallback por cantidad de
            # velas trajo solo las más recientes): extrapolar hacia ATRÁS con
            # la duración real de vela, igual que ya se hacía para el caso
            # "futuro". Antes esto aplastaba el punto al índice 0 sin más,
            # deformando la distancia real entre los dos extremos del dibujo.
            if t < new_candles[0]["t"]:
                target = parse_dt(t)
                edge = parse_dt(new_candles[0]["t"])
                if target is not None and edge is not None and tf_seconds:
                    extra_bars = int((edge - target).total_seconds() / tf_seconds)
                    return -max(extra_bars, 1)
                return 0

            for i, c in enumerate(new_candles):
                if c["t"] >= t:
                    return i
            # Posterior a la última vela descargada: extrapolar hacia
            # adelante con la duración real de vela del timeframe nuevo, así
            # se conserva la distancia relativa entre los dos puntos del dibujo.
            target = parse_dt(t)
            edge = parse_dt(new_candles[-1]["t"])
            if target is not None and edge is not None and tf_seconds:
                extra_bars = int((target - edge).total_seconds() / tf_seconds)
                return len(new_candles) - 1 + max(extra_bars, 1)
            return len(new_candles) - 1

        self.h_lines = [dict(h) for h in data.get("h_lines", [])]
        self.trendlines = [
            {"i1": time_to_idx(t["t1"]), "p1": t["p1"], "i2": time_to_idx(t["t2"]), "p2": t["p2"],
             "color": t.get("color", "#e0a800"), "width": t.get("width", 2)}
            for t in data.get("trendlines", [])
        ]
        self.rects = [
            {"i1": time_to_idx(r["t1"]), "p1": r["p1"], "i2": time_to_idx(r["t2"]), "p2": r["p2"],
             "color": r.get("color", "#c9a227"), "width": r.get("width", 1)}
            for r in data.get("rects", [])
        ]
        self.fibs = [
            {"i1": time_to_idx(f["t1"]), "p1": f["p1"], "i2": time_to_idx(f["t2"]), "p2": f["p2"]}
            for f in data.get("fibs", [])
        ]
        self.rr_boxes = [
            {"i1": time_to_idx(b["t1"]), "i2": time_to_idx(b["t2"]), "entry": b["entry"],
             "sl": b["sl"], "tp": b["tp"], "kind": b["kind"], "ratio": b["ratio"]}
            for b in data.get("rr_boxes", [])
        ]
        self.update()

    def clear_drawings(self):
        self.h_lines = []
        self.fibs = []
        self.trendlines = []
        self.rects = []
        self.rr_boxes = []
        self.update()

    def go_live(self):
        self.auto_follow = True
        self.update()

    # ── ICT detection cache ──
    def _get_ict_cache(self):
        """`display_candles()` devuelve un slice nuevo en cada llamada, así que no
        se puede usar `id(candles)` como parte de la clave de caché (el id() de un
        slice recién creado nunca coincide con el de la llamada anterior, aunque el
        contenido sea idéntico). Antes esto hacía que `detect_all()` — que incluye
        un escaneo de FVG sobre todo el histórico revelado — se recalculara en
        cada repintado (cada movimiento del mouse), no solo cuando cambiaban los
        datos. La clave ahora es (cantidad de velas, hora y close de la última) —
        el mismo patrón que ya usa `_get_ema` — así que solo se recalcula cuando de
        verdad hay una vela nueva o cambió el precio de la última (tick en vivo)."""
        candles = self.display_candles()
        if not candles:
            return {}
        key = (len(candles), candles[-1]["t"], candles[-1]["c"])
        if self._ict_cache.get("_key") == key:
            return self._ict_cache
        try:
            from core.ict_concepts import detect_all
            result = detect_all(candles)
            result["_key"] = key
            self._ict_cache = result
        except Exception as e:
            self._ict_cache = {"_key": key}
        return self._ict_cache

    def _draw_fvgs(self, p, fvgs):
        for fvg in fvgs:
            idx = fvg["idx"]
            if idx < self.view_start or idx >= self.view_start + self.view_count:
                continue
            x = self._x_of(idx, self.view_start, self._candle_w)
            y_top = self._y_of(fvg["gap_high"])
            y_bot = self._y_of(fvg["gap_low"])
            color = "#26a69a" if fvg["type"] == "bullish" else "#ef5350"
            alpha = 15 if fvg["mitigated"] else 35
            fill = QColor(color); fill.setAlpha(alpha)
            w2 = self._candle_w * 0.7
            p.fillRect(int(x - w2 / 2), int(y_top), int(w2), max(int(y_bot - y_top), 2), fill)
            pen = QPen(QColor(color), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(int(x - w2 / 2), int(y_top), int(x + w2 / 2), int(y_top))
            p.drawLine(int(x - w2 / 2), int(y_bot), int(x + w2 / 2), int(y_bot))
            label = "FVG+" if fvg["type"] == "bullish" else "FVG-"
            if fvg["mitigated"]:
                label += " (mit)"
            p.setPen(QColor(color))
            p.drawText(int(x - w2 / 2), int(y_top - 2), label)

    def _draw_order_blocks(self, p, obs, internal=False):
        """Dibuja un order block como caja que se extiende desde su vela de
        origen hasta el borde derecho visible -- igual que las cajas
        'extend.right' de LuxAlgo. `internal` solo cambia el estilo (mas
        sutil/delgado) para diferenciar el order block interno (micro) del
        swing (macro), igual que el indicador de referencia."""
        right_edge = self.view_start + self.view_count
        for ob in obs:
            idx = ob["idx"]
            if idx >= right_edge:
                continue
            x_left = self._x_of(max(idx, self.view_start), self.view_start, self._candle_w) - self._candle_w / 2
            x_right = self._x_of(right_edge - 1, self.view_start, self._candle_w) + self._candle_w / 2
            y_high = self._y_of(ob["high"])
            y_low = self._y_of(ob["low"])
            color = "#26a69a" if ob["type"] == "bullish" else "#ef5350"
            fill = QColor(color)
            fill.setAlpha(12 if internal else 30)
            p.fillRect(int(x_left), int(y_high), max(int(x_right - x_left), 1), max(int(y_low - y_high), 2), fill)
            pen = QPen(QColor(color), 1 if internal else 2, Qt.DashLine if internal else Qt.SolidLine)
            p.setPen(pen)
            p.drawRect(int(x_left), int(y_high), max(int(x_right - x_left), 1), max(int(y_low - y_high), 2))
            label = ("iOB+" if internal else "OB+") if ob["type"] == "bullish" else ("iOB-" if internal else "OB-")
            p.setPen(QColor(color))
            p.drawText(int(x_left) + 2, int(y_high) - 2, label)

    def _draw_structure(self, p, events, internal=False):
        """Dibuja BOS (continuacion de tendencia) y CHoCH (giro) -- estructura
        interna (micro, lookback corto) con linea punteada y etiqueta chica,
        estructura swing (macro) con linea solida y etiqueta mas grande, igual
        que la distincion visual del indicador de referencia."""
        right_edge = self.view_start + self.view_count
        for ev in events:
            if ev["idx"] < self.view_start or ev["pivot_idx"] >= right_edge:
                continue
            x1 = self._x_of(max(ev["pivot_idx"], self.view_start), self.view_start, self._candle_w)
            x2 = self._x_of(min(ev["idx"], right_edge - 1), self.view_start, self._candle_w)
            y = self._y_of(ev["level"])
            bullish = ev["type"].startswith("bullish")
            is_choch = ev["type"].endswith("choch")
            color = "#26a69a" if bullish else "#ef5350"
            width = (1 if internal else 2)
            style = Qt.DashLine if internal else Qt.DashDotLine if is_choch else Qt.SolidLine
            pen = QPen(QColor(color), width, style)
            p.setPen(pen)
            p.drawLine(int(x1), int(y), int(x2), int(y))
            p.setPen(QColor(color))
            tag = "CHoCH" if is_choch else "BOS"
            prefix = "i" if internal else ""
            arrow = "▲" if bullish else "▼"
            p.drawText(int((x1 + x2) / 2), int(y - 2), f"{prefix}{tag} {arrow}")

    def _draw_equal_highs_lows(self, p, equal_highs, equal_lows, w):
        """Dibuja Equal Highs (EQH) / Equal Lows (EQL): dos pivots casi al
        mismo precio -- una zona de liquidez, igual que el detector de
        referencia (pivots consecutivos del mismo tipo a menos de un umbral de
        ATR entre si)."""
        right_edge = self.view_start + self.view_count
        for eq in equal_highs:
            if eq["idx2"] < self.view_start or eq["idx1"] >= right_edge:
                continue
            x1 = self._x_of(max(eq["idx1"], self.view_start), self.view_start, self._candle_w)
            x2 = self._x_of(min(eq["idx2"], right_edge - 1), self.view_start, self._candle_w)
            y = self._y_of(max(eq["price1"], eq["price2"]))
            pen = QPen(QColor("#ef5350"), 1, Qt.DotLine)
            p.setPen(pen)
            p.drawLine(int(x1), int(y), int(x2), int(y))
            p.setPen(QColor("#ef5350"))
            p.drawText(int((x1 + x2) / 2), int(y - 2), "EQH")
        for eq in equal_lows:
            if eq["idx2"] < self.view_start or eq["idx1"] >= right_edge:
                continue
            x1 = self._x_of(max(eq["idx1"], self.view_start), self.view_start, self._candle_w)
            x2 = self._x_of(min(eq["idx2"], right_edge - 1), self.view_start, self._candle_w)
            y = self._y_of(min(eq["price1"], eq["price2"]))
            pen = QPen(QColor("#26a69a"), 1, Qt.DotLine)
            p.setPen(pen)
            p.drawLine(int(x1), int(y), int(x2), int(y))
            p.setPen(QColor("#26a69a"))
            p.drawText(int((x1 + x2) / 2), int(y + 10), "EQL")

    def _draw_pd_array(self, p, pd, w):
        if pd is None:
            return
        y_eq = self._y_of(pd["equilibrium"])
        y_prem = self._y_of(pd["premium"][1]) if pd["premium"][1] != pd["premium"][0] else y_eq
        y_disc = self._y_of(pd["discount"][0])
        if y_prem != y_eq:
            prem_fill = QColor("#ef5350"); prem_fill.setAlpha(12)
            p.fillRect(PAD_L, int(min(y_eq, y_prem)), w - PAD_L - PAD_R,
                       max(int(abs(y_eq - y_prem)), 2), prem_fill)
        if y_disc != y_eq:
            disc_fill = QColor("#26a69a"); disc_fill.setAlpha(12)
            p.fillRect(PAD_L, int(min(y_eq, y_disc)), w - PAD_L - PAD_R,
                       max(int(abs(y_eq - y_disc)), 2), disc_fill)
        pen = QPen(QColor("#c9a227"), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(PAD_L, int(y_eq), w - PAD_R, int(y_eq))
        p.setPen(QColor("#c9a227"))
        p.drawText(PAD_L + 2, int(y_eq - 2), "EQ 50%")
        p.setPen(QColor("#ef5350"))
        p.drawText(PAD_L + 2, int(min(y_eq, y_prem) - 2), "PREMIUM")
        p.setPen(QColor("#26a69a"))
        p.drawText(PAD_L + 2, int(max(y_eq, y_disc) - 2), "DISCOUNT")

    def _draw_ote(self, p, ote):
        if not ote:
            return
        y_top = self._y_of(ote["high"])
        y_bot = self._y_of(ote["low"])
        fill = QColor("#c9a227"); fill.setAlpha(18)
        p.fillRect(PAD_L, int(y_top), self.width() - PAD_L - PAD_R,
                   max(int(y_bot - y_top), 2), fill)
        pen = QPen(QColor("#c9a227"), 1)
        p.setPen(pen)
        p.drawText(PAD_L + 2, int(y_top - 2), "OTE (0.618-0.79)")

    def _draw_killzones(self, p, w):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        from core.ict_concepts import current_killzones
        zones = current_killzones(now)
        if zones:
            text = "Killzones activas: " + ", ".join(zones)
            p.setPen(QColor("#c9a227"))
            p.drawText(PAD_L + 2, PAD_T + 12, text)
            self.killzone_label.setText(" | ".join(zones))
            self.killzone_label.adjustSize()
            self.killzone_label.move(self.width() - self.killzone_label.width() - 4, PAD_T + 4)
            self.killzone_label.setVisible(True)
        else:
            self.killzone_label.setVisible(False)
