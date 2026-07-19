"""Workers en hilo aparte para no congelar la interfaz durante:
- la descarga de histórico desde MT5 (FetchWorker),
- el sondeo del precio en vivo (LiveTickWorker),
- la lectura de un CSV grande (CsvLoadWorker).

Todos capturan cualquier excepción inesperada y la reportan por señal de error.
Antes, una excepción no controlada dentro de `run()` dejaba el hilo terminado en
silencio, sin emitir ninguna señal — y como el código que lanza el worker deja los
controles de carga deshabilitados hasta que llega una señal, la interfaz quedaba
"Cargando…" para siempre sin ningún aviso (ver auditoría técnica, punto 2.2).
"""
from PySide6.QtCore import QThread, Signal

from . import mt5_data
from .data_utils import parse_csv


class FetchWorker(QThread):
    """Corre las llamadas a MT5 en un hilo aparte — pedir muchas velas (sobre todo en
    D1/H4) puede tardar bastante si el bróker tiene que descargar historial del
    servidor, y eso NUNCA debe congelar la ventana principal."""
    finished_ok = Signal(list)
    finished_err = Signal(str)

    def __init__(self, mode, symbol, tf, count=None, date_from=None, date_to=None):
        super().__init__()
        self.mode = mode
        self.symbol = symbol
        self.tf = tf
        self.count = count
        self.date_from = date_from
        self.date_to = date_to

    def run(self):
        try:
            if self.mode == "range":
                candles, err = mt5_data.get_rates_range(self.symbol, self.tf, self.date_from, self.date_to)
            else:
                candles, err = mt5_data.get_rates(self.symbol, self.tf, self.count)
        except Exception as e:
            self.finished_err.emit(f"Error inesperado al consultar MT5: {e}")
            return
        if err:
            self.finished_err.emit(err)
        else:
            self.finished_ok.emit(candles)


class LiveTickWorker(QThread):
    """Sondea solo las velas más recientes cada pocos segundos, en un hilo aparte,
    para actualizar el gráfico en vivo sin congelar la interfaz."""
    got_bars = Signal(list)
    failed = Signal(str)

    def __init__(self, symbol, tf, count=2):
        super().__init__()
        self.symbol = symbol
        self.tf = tf
        self.count = count

    def run(self):
        try:
            candles, err = mt5_data.get_latest_bars(self.symbol, self.tf, self.count)
        except Exception as e:
            self.failed.emit(f"Error inesperado al sondear precio en vivo: {e}")
            return
        if err:
            self.failed.emit(err)
        else:
            self.got_bars.emit(candles)


class CsvLoadWorker(QThread):
    """Lee un CSV/TXT exportado de MT5 en un hilo aparte. Antes `parse_csv` se
    llamaba directamente en el hilo principal: con un archivo de varios cientos de
    miles de líneas, la ventana se congelaba durante toda la lectura."""
    finished_ok = Signal(list)
    finished_err = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            candles = parse_csv(self.path)
        except Exception as e:
            self.finished_err.emit(f"No se pudo leer el archivo: {e}")
            return
        self.finished_ok.emit(candles)
