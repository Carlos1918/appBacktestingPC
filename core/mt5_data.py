"""Conexión directa al terminal MT5 en ejecución (Windows) — sin exportar CSV a mano.

IMPORTANTE — concurrencia:
Todas las llamadas a la librería `MetaTrader5` pasan por `_mt5_lock`. La conexión
IPC con el terminal es un recurso compartido por proceso, y la librería oficial
de MetaQuotes no garantiza ser segura ante llamadas concurrentes desde varios
hilos. Esta app dispara llamadas a MT5 desde dos hilos distintos en paralelo
(descarga de histórico y sondeo del precio en vivo), así que sin este lock existe
una condición de carrera real: dos hilos podrían llamar a la API al mismo tiempo
y corromper la respuesta o colgar la conexión (ver auditoría técnica, punto 2.1).

El lock se toma solo alrededor de la llamada nativa a `mt5.*`, no durante el
formateo posterior de los datos, para no retener el lock más tiempo del necesario.
"""
import datetime
import threading

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    _MT5_IMPORT_ERROR = None
except Exception as e:
    # Antes solo se atrapaba ImportError y se perdía el motivo real. Un caso real
    # visto en producción: MetaTrader5 importaba pero fallaba en cascada porque
    # PyInstaller no había empaquetado numpy completo ("numpy._core.multiarray
    # failed to import") — con solo "ImportError" ese detalle no se veía en
    # ningún lado. Ahora se guarda el motivo real para mostrarlo en el mensaje
    # de error de connect(), sin tener que reconstruir el .exe en modo consola
    # para diagnosticarlo.
    MT5_AVAILABLE = False
    _MT5_IMPORT_ERROR = repr(e)

TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}

_mt5_lock = threading.Lock()


def _tf_const(key):
    mapping = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(key, mt5.TIMEFRAME_M15)


def connect():
    """Se conecta a la instancia de MT5 que ya esté abierta y logueada en esta PC."""
    if not MT5_AVAILABLE:
        detail = f" Detalle técnico: {_MT5_IMPORT_ERROR}" if _MT5_IMPORT_ERROR else ""
        return False, ("La librería 'MetaTrader5' no está instalada o no es compatible "
                        "con este sistema operativo (solo funciona en Windows). "
                        "Corre: pip install MetaTrader5" + detail)
    with _mt5_lock:
        ok = mt5.initialize()
        err = None if ok else mt5.last_error()
    if not ok:
        return False, (f"No se pudo conectar al terminal MT5 (código {err}). "
                        "Verifica que MT5 esté abierto y logueado en una cuenta antes de conectar.")
    return True, None


def disconnect():
    if MT5_AVAILABLE:
        with _mt5_lock:
            mt5.shutdown()


def list_symbols():
    """Devuelve los símbolos visibles en el Market Watch del terminal conectado."""
    if not MT5_AVAILABLE:
        return []
    with _mt5_lock:
        syms = mt5.symbols_get()
    if syms is None:
        return []
    return sorted(s.name for s in syms if s.visible)


def get_contract_size(symbol):
    """Tamaño de contrato real del símbolo (para calcular P&L en dinero). Si no se
    puede consultar, usa un valor por defecto razonable en vez de fallar."""
    if not MT5_AVAILABLE:
        return 100.0
    with _mt5_lock:
        info = mt5.symbol_info(symbol)
    if info is None or not getattr(info, "trade_contract_size", None):
        return 100.0
    return float(info.trade_contract_size)


def get_symbol_digits(symbol):
    """Dígitos decimales reales del símbolo, consultados a MT5 — se usan para
    formatear precios sin adivinar por la magnitud del número (antes se usaba
    una heurística: '.2f si el precio > 100, si no .5f', que podía quedar mal
    para símbolos exóticos). Devuelve None si no se puede consultar; en ese caso
    quien llama debe caer a un formateo por defecto (ver core/formatting.py)."""
    if not MT5_AVAILABLE:
        return None
    with _mt5_lock:
        info = mt5.symbol_info(symbol)
    if info is None or not hasattr(info, "digits"):
        return None
    return int(info.digits)


def get_latest_bars(symbol, timeframe_key, count=2):
    """Trae solo las últimas velas — pensado para sondear el precio en vivo cada
    pocos segundos sin pedir todo el histórico de nuevo."""
    return get_rates(symbol, timeframe_key, count)


def get_rates(symbol, timeframe_key, count=3000):
    """Trae velas reales (ya agregadas por el broker) para symbol+timeframe."""
    if not MT5_AVAILABLE:
        return None, "MetaTrader5 no disponible en este sistema."
    with _mt5_lock:
        if not mt5.symbol_select(symbol, True):
            return None, f"No se pudo seleccionar el símbolo '{symbol}' en el Market Watch."
        tf = _tf_const(timeframe_key)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None, (f"Sin datos históricos para {symbol} en {timeframe_key}. "
                       "Prueba abriendo ese símbolo/timeframe manualmente en MT5 primero "
                       "para forzar la descarga del historial desde el servidor.")
    out = []
    for r in rates:
        dt = datetime.datetime.fromtimestamp(int(r["time"]), tz=datetime.timezone.utc)
        out.append({
            "t": dt.strftime("%Y.%m.%d %H:%M"),
            "o": float(r["open"]), "h": float(r["high"]),
            "l": float(r["low"]), "c": float(r["close"]),
        })
    return out, None


def get_rates_range(symbol, timeframe_key, date_from, date_to):
    """Trae velas reales entre dos fechas — se usa para reubicar el replay al cambiar
    de timeframe, garantizando que el punto que queríamos conservar quede cubierto
    sin importar qué tan corto sea el rango que cubriría la misma cantidad de barras."""
    if not MT5_AVAILABLE:
        return None, "MetaTrader5 no disponible en este sistema."
    with _mt5_lock:
        if not mt5.symbol_select(symbol, True):
            return None, f"No se pudo seleccionar el símbolo '{symbol}' en el Market Watch."
        tf = _tf_const(timeframe_key)
        rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
    if rates is None or len(rates) == 0:
        return None, (f"Sin datos históricos para {symbol} en {timeframe_key} en ese rango de fechas.")
    out = []
    for r in rates:
        dt = datetime.datetime.fromtimestamp(int(r["time"]), tz=datetime.timezone.utc)
        out.append({
            "t": dt.strftime("%Y.%m.%d %H:%M"),
            "o": float(r["open"]), "h": float(r["high"]),
            "l": float(r["low"]), "c": float(r["close"]),
        })
    return out, None
