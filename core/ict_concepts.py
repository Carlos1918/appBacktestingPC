"""Deteccion de conceptos ICT / Smart Money Concepts (SMC).

La logica de este modulo replica, adaptada a listas de velas en Python, el
indicador "Smart Money Concepts (SMC) [LuxAlgo]" (open-source, ~152K usos en
TradingView -- la referencia de facto de la comunidad SMC/ICT). Cada funcion
documenta a que parte del script Pine original corresponde para que se pueda
verificar/actualizar contra la fuente.

Conceptos que replica:
  - Estructura de mercado interna (micro, lookback corto) y swing (macro,
    lookback largo), cada una con BOS (Break of Structure, continuacion) y
    CHoCH (Change of Character, giro) -- ver `_structure_breaks`.
  - Order Blocks internos y swing, creados en cada ruptura de estructura sobre
    la vela de extremo mas marcado del tramo previo, excluyendo velas de alta
    volatilidad del calculo -- ver `_order_blocks`.
  - Equal Highs / Equal Lows (liquidez): pivots consecutivos del mismo tipo a
    menos de un umbral (fraccion de ATR) de distancia -- ver `_equal_highs_lows`.
  - Fair Value Gap con umbral automatico basado en el movimiento historico
    promedio -- ver `detect_fvgs`.
  - Premium/Discount sobre el rango "trailing" (ultimo swing confirmado,
    extendido por los maximos/minimos posteriores) -- ver `_trailing_extremes`.
  - OTE (Optimal Trade Entry): no es parte del script de LuxAlgo, se mantiene
    la implementacion propia ya verificada contra la metodologia ICT.
"""
import datetime

# ── parametros (iguales a los valores por defecto de LuxAlgo) ──
INTERNAL_LENGTH       = 5     # lookback de estructura interna (swingsLengthInput interno = 5 en LuxAlgo)
SWING_LENGTH          = 50    # lookback de estructura swing/macro (swingsLengthInput = 50 por defecto)
EQUAL_HL_LENGTH        = 3     # velas para confirmar un pivot de EQH/EQL (equalHighsLowsLengthInput)
EQUAL_HL_THRESHOLD     = 0.1   # umbral en fracciones de ATR (equalHighsLowsThresholdInput)
ATR_PERIOD             = 200   # ta.atr(200) en el original
ORDER_BLOCK_VOL_MULT   = 2     # vela de alta volatilidad si (h-l) >= 2*ATR -- excluida del calculo de OB
FVG_THRESHOLD_MULT     = 2     # umbral automatico del FVG = 2x el promedio historico del cuerpo
MAX_ORDER_BLOCKS       = 5     # cuantos order blocks (mas recientes) se muestran, igual que LuxAlgo

# ── Killzones (horario GMT) ──
KILLZONES = {
    "Asia":         (0, 9),
    "London":       (7, 16),
    "NY":           (12, 21),
    "London Close": (15, 16),
    "NY Close":     (20, 21),
}

def current_killzones(dt=None):
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    return [name for name, (s, e) in KILLZONES.items() if s <= dt.hour < e]


# ── ATR (Wilder RMA, igual que ta.atr() de Pine) ──
def _atr(candles, period=ATR_PERIOD):
    n = len(candles)
    atr = [0.0] * n
    if n == 0:
        return atr
    tr = [0.0] * n
    for i in range(n):
        h, l = candles[i]["h"], candles[i]["l"]
        prev_c = candles[i - 1]["c"] if i > 0 else candles[i]["o"]
        tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

    if n < period:
        running = 0.0
        for i in range(n):
            running += tr[i]
            atr[i] = running / (i + 1)
        return atr

    running = 0.0
    for i in range(period - 1):
        running += tr[i]
        atr[i] = running / (i + 1)
    seed = (running + tr[period - 1]) / period
    atr[period - 1] = seed
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ── deteccion de pivots (swing points) por "leg" -- replica leg()/startOfNewLeg() ──
def _leg_pivots(candles, size):
    """Un pivot alto/bajo se confirma `size` velas despues de ocurrir, una vez
    que ninguna de esas `size` velas siguientes supero su extremo (equivalente
    a leg()/startOfNewLeg() del script original). Devuelve eventos en el orden
    en que se CONFIRMAN (con `size` velas de retraso respecto a cuando
    ocurrieron), cada uno con: kind ('high'/'low'), idx (indice real del
    pivot), price, confirmed_idx (vela en la que se confirmo)."""
    n = len(candles)
    pivots = []
    leg = 0  # 0 = pierna bajista (biscando un swing high), 1 = alcista (buscando swing low)
    for i in range(size, n):
        window_highs = [candles[j]["h"] for j in range(i - size + 1, i + 1)]
        window_lows  = [candles[j]["l"] for j in range(i - size + 1, i + 1)]
        new_leg_high = candles[i - size]["h"] > max(window_highs)
        new_leg_low  = candles[i - size]["l"] < min(window_lows)

        new_leg = leg
        if new_leg_high:
            new_leg = 0
        elif new_leg_low:
            new_leg = 1

        if new_leg != leg:
            pivot_idx = i - size
            if new_leg == 1:
                pivots.append({"kind": "low", "idx": pivot_idx, "price": candles[pivot_idx]["l"], "confirmed_idx": i})
            else:
                pivots.append({"kind": "high", "idx": pivot_idx, "price": candles[pivot_idx]["h"], "confirmed_idx": i})
            leg = new_leg
    return pivots


# ── BOS / CHoCH -- replica displayStructure() ──
def _structure_breaks(candles, pivots):
    """Recorre las velas en orden cronologico manteniendo el ultimo pivot alto
    y bajo vigente (se actualiza cada vez que `pivots` confirma uno nuevo) y el
    sesgo de tendencia actual. Cuando el cierre cruza el pivot alto vigente (y
    ese pivot no fue cruzado antes), es BOS si la tendencia ya era alcista, o
    CHoCH si estaba bajista -- y simetrico para el pivot bajo. Replica
    exactamente displayStructure()/getCurrentStructure() del script original."""
    n = len(candles)
    events = []
    by_confirmed_idx = {}
    for p in pivots:
        by_confirmed_idx.setdefault(p["confirmed_idx"], []).append(p)

    high_pivot = None
    low_pivot = None
    trend = 0  # 0 = sin sesgo aun, 1 = alcista, -1 = bajista

    start = min((p["confirmed_idx"] for p in pivots), default=n)
    for i in range(start, n):
        for p in by_confirmed_idx.get(i, []):
            if p["kind"] == "high":
                high_pivot = {"idx": p["idx"], "price": p["price"], "crossed": False}
            else:
                low_pivot = {"idx": p["idx"], "price": p["price"], "crossed": False}

        prev_close = candles[i - 1]["c"] if i > 0 else candles[i]["o"]

        if high_pivot is not None and not high_pivot["crossed"]:
            if prev_close <= high_pivot["price"] < candles[i]["c"]:
                tag = "choch" if trend == -1 else "bos"
                events.append({"type": f"bullish_{tag}", "idx": i, "level": high_pivot["price"], "pivot_idx": high_pivot["idx"]})
                high_pivot["crossed"] = True
                trend = 1

        if low_pivot is not None and not low_pivot["crossed"]:
            if prev_close >= low_pivot["price"] > candles[i]["c"]:
                tag = "choch" if trend == 1 else "bos"
                events.append({"type": f"bearish_{tag}", "idx": i, "level": low_pivot["price"], "pivot_idx": low_pivot["idx"]})
                low_pivot["crossed"] = True
                trend = -1

    return events


# ── Order Blocks -- replica storeOrdeBlock()/deleteOrderBlocks() ──
def _order_blocks(candles, structure_events, atr):
    """Cada BOS/CHoCH crea un order block sobre la vela de extremo mas marcado
    del tramo [pivot_idx, break_idx) previo a la ruptura: la de low mas bajo
    para rupturas alcistas, la de high mas alto para rupturas bajistas -- pero
    usando 'parsed high/low', que excluye velas de alta volatilidad (rango >=
    2x ATR) del calculo sustituyendo su high por su low (y viceversa), para
    que un spike puntual no termine marcado como order block."""
    n = len(candles)
    parsed_high = [0.0] * n
    parsed_low = [0.0] * n
    for i in range(n):
        h, l = candles[i]["h"], candles[i]["l"]
        a = atr[i]
        high_vol = a > 0 and (h - l) >= ORDER_BLOCK_VOL_MULT * a
        parsed_high[i] = l if high_vol else h
        parsed_low[i] = h if high_vol else l

    blocks = []
    for ev in structure_events:
        pivot_idx, break_idx = ev["pivot_idx"], ev["idx"]
        if break_idx <= pivot_idx:
            continue
        bias = "bullish" if ev["type"].startswith("bullish") else "bearish"

        if bias == "bearish":
            segment = parsed_high[pivot_idx:break_idx]
            rel = segment.index(max(segment))
        else:
            segment = parsed_low[pivot_idx:break_idx]
            rel = segment.index(min(segment))
        ob_idx = pivot_idx + rel

        blocks.append({
            "type": bias,
            "idx": ob_idx,
            "high": candles[ob_idx]["h"],
            "low": candles[ob_idx]["l"],
            "structure_idx": break_idx,
            "mitigated": False,
        })

    # mitigacion: se usa el rango completo (high/low) de la vela, no el cuerpo
    # -- un OB bajista se invalida cuando el precio rompe por encima de su
    # high, uno alcista cuando rompe por debajo de su low.
    for ob in blocks:
        for c in candles[ob["structure_idx"] + 1:]:
            if ob["type"] == "bearish" and c["h"] > ob["high"]:
                ob["mitigated"] = True
                break
            if ob["type"] == "bullish" and c["l"] < ob["low"]:
                ob["mitigated"] = True
                break

    # solo se muestran los N mas recientes (no mitigados primero), igual que
    # el limite "Order Blocks to display" de LuxAlgo (5 por defecto)
    unmitigated = [b for b in blocks if not b["mitigated"]]
    unmitigated.sort(key=lambda b: b["idx"], reverse=True)
    return unmitigated[:MAX_ORDER_BLOCKS]


# ── Equal Highs / Equal Lows -- replica el modo equalHighLow de getCurrentStructure() ──
def _equal_highs_lows(candles, atr, length=EQUAL_HL_LENGTH, threshold=EQUAL_HL_THRESHOLD):
    """Usa el mismo detector de pivots que la estructura, pero con un lookback
    corto, y compara cada pivot nuevo contra el INMEDIATAMENTE anterior del
    mismo tipo: si estan a menos de threshold*ATR de distancia, se marcan como
    'iguales' -- una zona de liquidez (EQH si son highs, EQL si son lows)."""
    pivots = _leg_pivots(candles, length)
    eqh, eql = [], []
    last_high = last_low = None

    for p in pivots:
        a = atr[p["confirmed_idx"]]
        if p["kind"] == "high":
            if last_high is not None and a > 0 and abs(last_high["price"] - p["price"]) < threshold * a:
                eqh.append({
                    "idx1": last_high["idx"], "idx2": p["idx"],
                    "price1": last_high["price"], "price2": p["price"],
                    "confirmed_idx": p["confirmed_idx"],
                })
            last_high = p
        else:
            if last_low is not None and a > 0 and abs(last_low["price"] - p["price"]) < threshold * a:
                eql.append({
                    "idx1": last_low["idx"], "idx2": p["idx"],
                    "price1": last_low["price"], "price2": p["price"],
                    "confirmed_idx": p["confirmed_idx"],
                })
            last_low = p

    return eqh, eql


# ── Fair Value Gap (FVG) -- replica drawFairValueGaps()/deleteFairValueGaps() ──
def detect_fvgs(candles, threshold_mult=FVG_THRESHOLD_MULT, auto_threshold=True):
    """FVG de 3 velas: c1 (i-2), c2 (i-1, vela de impulso), c3 (i).

    Reglas (igual que LuxAlgo):
      - Bullish: c3.low > c1.high (hueco alcista) Y c2.close > c1.high
        (el cierre de la vela de impulso tambien supera el extremo de c1)
        Y el cuerpo de c2 (en %) supera el umbral.
      - Bearish: simetrico, con c3.high < c1.low y c2.close < c1.low.
      - Umbral automatico: 2x el promedio historico acumulado del |cuerpo%|
        de todas las velas hasta ese punto (en vez de un % fijo arbitrario) --
        asi el filtro se adapta a la volatilidad real del simbolo/timeframe.
      - Mitigacion: replica exactamente la asimetria del original -- un FVG
        alcista se invalida cuando el precio perfora POR COMPLETO hacia abajo
        (low < limite inferior del hueco), uno bajista se invalida en cuanto
        el precio toca el limite inferior del hueco desde abajo (high > ese
        mismo limite). No es simetrico en el original tampoco; se mantiene tal
        cual para ser fiel a la referencia.
    """
    n = len(candles)
    results = []
    if n < 3:
        return results

    body_pct = [0.0] * n
    for i in range(n):
        o = candles[i]["o"]
        body_pct[i] = (candles[i]["c"] - o) / o if o else 0.0

    running_avg_abs = [0.0] * n
    cum_abs = 0.0
    for i in range(n):
        cum_abs += abs(body_pct[i])
        running_avg_abs[i] = cum_abs / (i + 1)

    for i in range(2, n):
        c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
        mid_body_pct = body_pct[i - 1]
        threshold = threshold_mult * running_avg_abs[i - 1] if auto_threshold else 0.0

        if c3["l"] > c1["h"] and c2["c"] > c1["h"] and mid_body_pct > threshold:
            gap_high, gap_low = c3["l"], c1["h"]
            results.append({
                "type": "bullish", "idx": i - 1,
                "gap_high": gap_high, "gap_low": gap_low,
                "gap_size": gap_high - gap_low, "mitigated": False,
            })
            continue

        if c3["h"] < c1["l"] and c2["c"] < c1["l"] and -mid_body_pct > threshold:
            gap_high, gap_low = c1["l"], c3["h"]
            results.append({
                "type": "bearish", "idx": i - 1,
                "gap_high": gap_high, "gap_low": gap_low,
                "gap_size": gap_high - gap_low, "mitigated": False,
            })

    for fvg in results:
        gl = fvg["gap_low"]
        for c in candles[fvg["idx"] + 1:]:
            if fvg["type"] == "bullish" and c["l"] < gl:
                fvg["mitigated"] = True
                break
            if fvg["type"] == "bearish" and c["h"] > gl:
                fvg["mitigated"] = True
                break

    return results


# ── Premium / Discount (rango "trailing") -- replica updateTrailingExtremes() ──
def calc_pd_array(high, low):
    """Zona Premium/Discount ICT a partir de un rango dado.

    - Equilibrium (50%): punto medio
    - Premium  (50%-100%): zona de venta
    - Discount (0%-50%):   zona de compra
    """
    if high == low:
        return None
    eq = (high + low) / 2
    return {
        "high": high,
        "low": low,
        "equilibrium": eq,
        "premium": (eq, high),
        "discount": (low, eq),
    }


def _trailing_extremes(candles, swing_pivots):
    """Rango vigente de negociacion: arranca en el ultimo swing high/low
    confirmado (lookback SWING_LENGTH) y se extiende con el maximo/minimo de
    las velas siguientes hasta que un nuevo swing del mismo tipo lo reemplaza
    -- exactamente updateTrailingExtremes() + los resets dentro de
    getCurrentStructure() del script original. Devuelve (top, bottom) segun el
    estado al final del historial dado, o (None, None) si no hay suficientes
    datos."""
    n = len(candles)
    by_confirmed_idx = {}
    for p in swing_pivots:
        by_confirmed_idx.setdefault(p["confirmed_idx"], []).append(p)

    top = bottom = None
    for i in range(n):
        if top is not None:
            top = max(top, candles[i]["h"])
        if bottom is not None:
            bottom = min(bottom, candles[i]["l"])
        for p in by_confirmed_idx.get(i, []):
            if p["kind"] == "high":
                top = p["price"]
            else:
                bottom = p["price"]

    return top, bottom


# ── OTE (Optimal Trade Entry) ──
# No es parte del script de LuxAlgo (esa herramienta no incluye OTE) -- se
# mantiene la logica propia, ya verificada: zona 61.8%-79% medida HACIA ATRAS
# desde el extremo mas reciente del tramo (discount para bullish, premium para
# bearish), que es como ICT ensenia a leer el retroceso.
def calc_ote(high, low, kind="bullish"):
    if high == low:
        return None
    rng = high - low
    if kind == "bullish":
        f618 = high - rng * 0.618
        f79 = high - rng * 0.79
    else:
        f618 = low + rng * 0.618
        f79 = low + rng * 0.79
    return {"high": max(f618, f79), "low": min(f618, f79)}


# ── Detector completo ──
def detect_all(candles):
    """Ejecuta todas las detecciones ICT/SMC replicando la logica del
    indicador de referencia (LuxAlgo). Retorna dict con todas las detecciones,
    o {} si no hay suficientes datos."""
    if not candles or len(candles) < 20:
        return {}

    atr = _atr(candles)

    internal_pivots = _leg_pivots(candles, INTERNAL_LENGTH)
    internal_structure = _structure_breaks(candles, internal_pivots)
    internal_order_blocks = _order_blocks(candles, internal_structure, atr)

    swing_pivots = _leg_pivots(candles, SWING_LENGTH)
    swing_structure = _structure_breaks(candles, swing_pivots)
    swing_order_blocks = _order_blocks(candles, swing_structure, atr)

    fvgs = detect_fvgs(candles)
    equal_highs, equal_lows = _equal_highs_lows(candles, atr)

    top, bottom = _trailing_extremes(candles, swing_pivots)
    pd = calc_pd_array(top, bottom) if top is not None and bottom is not None else None
    if pd is None:
        last_60 = candles[-60:] if len(candles) >= 60 else candles
        pd = calc_pd_array(max(c["h"] for c in last_60), min(c["l"] for c in last_60))

    # OTE: usa el ultimo swing high y el ultimo swing low confirmados: el que
    # haya ocurrido MAS RECIENTE (por indice) marca el sesgo del tramo actual.
    ote = None
    swing_highs_list = [p for p in swing_pivots if p["kind"] == "high"]
    swing_lows_list = [p for p in swing_pivots if p["kind"] == "low"]
    if swing_highs_list and swing_lows_list:
        last_sh = swing_highs_list[-1]
        last_sl = swing_lows_list[-1]
        move_high = max(last_sh["price"], last_sl["price"])
        move_low = min(last_sh["price"], last_sl["price"])
        if move_high != move_low:
            kind = "bullish" if last_sl["idx"] > last_sh["idx"] else "bearish"
            ote = calc_ote(move_high, move_low, kind)

    return {
        "internal_structure": internal_structure,
        "swing_structure": swing_structure,
        "internal_order_blocks": internal_order_blocks,
        "swing_order_blocks": swing_order_blocks,
        "fvgs": fvgs,
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "swing_highs": [{"idx": p["idx"], "price": p["price"]} for p in swing_highs_list],
        "swing_lows": [{"idx": p["idx"], "price": p["price"]} for p in swing_lows_list],
        "pd_array": pd,
        "ote": ote,
    }
