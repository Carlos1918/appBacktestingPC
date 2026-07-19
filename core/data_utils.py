"""Utilidades de carga y cálculo sobre datos históricos (MT5 / CSV genérico)."""
import re


def parse_csv(path):
    """Lee un archivo exportado de MT5 (tabulado) o CSV estándar con encabezados.
    Devuelve una lista de dicts: {t, o, h, l, c}
    """
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        raw = f.read()

    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return []

    delim = "\t" if "\t" in lines[0] else ("," if lines[0].count(",") > 2 else None)

    def split(line):
        if delim:
            return line.split(delim)
        return re.split(r"\s+", line.strip())

    first_cols = split(lines[0])
    looks_like_header = bool(re.search(r"[a-zA-Z]", first_cols[0])) and not re.match(
        r"^\d{4}[.\-/]\d{2}", first_cols[0]
    )

    col_map = {"date": 0, "time": 1, "open": 2, "high": 3, "low": 4, "close": 5}
    start_idx = 0
    if looks_like_header:
        start_idx = 1
        norm = [c.strip().lower().strip("<>") for c in first_cols]

        def find(names):
            for n in names:
                if n in norm:
                    return norm.index(n)
            return -1

        d, t = find(["date"]), find(["time"])
        o, h, l, c = find(["open"]), find(["high"]), find(["low"]), find(["close"])
        if min(o, h, l, c) >= 0:
            col_map = {
                "date": d if d >= 0 else 0,
                "time": t if t >= 0 else 1,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }

    out = []
    for line in lines[start_idx:]:
        cols = split(line)
        try:
            o = float(cols[col_map["open"]])
            h = float(cols[col_map["high"]])
            l = float(cols[col_map["low"]])
            c = float(cols[col_map["close"]])
        except (ValueError, IndexError):
            continue
        date_part = cols[col_map["date"]] if col_map["date"] < len(cols) else ""
        time_part = cols[col_map["time"]] if col_map["time"] < len(cols) else ""
        label = (date_part + " " + time_part).strip()
        out.append({"t": label, "o": o, "h": h, "l": l, "c": c})
    return out


def compute_ema(candles, period):
    """EMA completa sobre la lista de velas dada. Devuelve lista alineada (None
    donde no hay dato todavía). Es O(n) — se usa como cálculo de referencia y como
    "recompute" completo dentro del caché incremental de ChartWidget; el widget no
    debe llamar a esta función en cada frame sobre el histórico completo (ver
    `chart/chart_widget.py::_get_ema`, que cachea y solo extiende el cálculo cuando
    llegan velas nuevas)."""
    n = len(candles)
    out = [None] * n
    if n < period:
        return out
    k = 2 / (period + 1)
    ema = sum(c["c"] for c in candles[:period]) / period
    out[period - 1] = ema
    for i in range(period, n):
        ema = candles[i]["c"] * k + ema * (1 - k)
        out[i] = ema
    return out
