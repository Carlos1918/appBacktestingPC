"""Deteccion de conceptos ICT (Inner Circle Trader).

Cada detector aplica criterios explicitos de la metodologia ICT para evitar
falsos positivos. Ningun patron se marca solo porque los numeros se alinean
por casualidad.
"""
import datetime

# ── parametros globales de sensibilidad ──
MIN_GAP_FRAC  = 0.0002   # gap minimo del FVG como fraccion del precio
MIN_IMPULSE   = 0.002    # impulso minimo para Order Block (0.2%)
MIN_BODY_RATIO = 0.4     # cuerpo minimo de la vela OB respecto a su rango
SWING_LOOKBACK = 3       # velas a cada lado para confirmar swing point
CHoCH_LOOKAHEAD = 30     # max velas hacia adelante para buscar CHoCH

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


# ── utilidades ──
def _body_pct(c):
    rng = c["h"] - c["l"]
    return abs(c["c"] - c["o"]) / rng if rng else 0

def _range_pct(c):
    return (c["h"] - c["l"]) / ((c["h"] + c["l"]) / 2) if (c["h"] + c["l"]) else 0


# ── FVG (Fair Value Gap) ──
def detect_fvgs(candles, max_lookback=None):
    """FVG real de ICT: 3 velas consecutivas donde las sombras de la vela 1 y 3
    NO se solapan, dejando un 'hueco' o ineficiencia.

    Reglas:
      - 3 velas: c1 (i-2), c2 (i-1), c3 (i)
      - Bullish FVG: c1.high < c3.low  (gap alcista entre c1 y c3)
      - Bearish FVG: c1.low  > c3.high (gap bajista entre c1 y c3)
      - El gap debe superar MIN_GAP_FRAC * precio_medio
      - La vela 2 debe tener cuerpo en la direccion del gap (rechazo)
    """
    n = len(candles)
    results = []
    start = max(2, (n - max_lookback) if max_lookback else 2)
    for i in range(start, n):
        c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
        avg_price = (c1["h"] + c1["l"] + c3["h"] + c3["l"]) / 4
        min_gap = avg_price * MIN_GAP_FRAC

        # Bullish FVG: gap al alza, c2 bajista (rechazo)
        gap = c3["l"] - c1["h"]
        if gap > min_gap and c2["c"] < c2["o"]:
            results.append({
                "type": "bullish",
                "idx": i - 1,
                "gap_high": c3["l"],
                "gap_low":  c1["h"],
                "gap_size": gap,
                "mitigated": False,
            })
            continue

        # Bearish FVG: gap a la baja, c2 alcista (rechazo)
        gap = c1["l"] - c3["h"]
        if gap > min_gap and c2["c"] > c2["o"]:
            results.append({
                "type": "bearish",
                "idx": i - 1,
                "gap_high": c1["l"],
                "gap_low":  c3["h"],
                "gap_size": gap,
                "mitigated": False,
            })

    # Marcar FVGs mitigados (el precio volvio a la zona del gap)
    for fvg in results:
        gh, gl = fvg["gap_high"], fvg["gap_low"]
        for c in candles[fvg["idx"] + 1:]:
            if c["l"] <= gh and c["h"] >= gl:
                fvg["mitigated"] = True
                break

    return results


# ── Order Block (OB) ──
def detect_order_blocks(candles, lookback=60):
    """Order Block ICT: la ULTIMA vela en direccion opuesta antes de un
    impulso fuerte de 3+ velas consecutivas en la misma direccion.

    Reglas:
      - Bullish OB: vela bajista (o con cuerpo pequenio) seguida de 3 velas
        alcistas consecutivas con impulso agregado > MIN_IMPULSE
      - Bearish OB: vela alcista seguida de 3 velas bajistas consecutivas
      - La OB debe tener cuerpo significativo (MIN_BODY_RATIO)
      - El impulso debe ser >= MIN_IMPULSE desde el cierre de la OB
      - Solo la ULTIMA vela contraria se marca (no todas las del medio)
    """
    n = len(candles)
    results = []
    start = max(1, n - lookback) if lookback else 1

    i = start
    while i < n - 3:
        ob_candle = candles[i]
        body_ratio = _body_pct(ob_candle)

        if body_ratio < MIN_BODY_RATIO:
            i += 1
            continue

        # Busca impulso de 3 velas en direccion contraria
        if ob_candle["c"] < ob_candle["o"]:  # bajista -> posible OB alcista
            if all(candles[i + j]["c"] > candles[i + j]["o"] for j in range(1, 4)):
                move = (candles[i + 3]["c"] - ob_candle["c"]) / ob_candle["c"]
                if move > MIN_IMPULSE:
                    # Asegurar que es la ULTIMA bajista antes del impulso
                    if i == 0 or candles[i - 1]["c"] >= candles[i - 1]["o"]:
                        results.append({
                            "type": "bullish",
                            "idx": i,
                            "high": ob_candle["h"],
                            "low":  ob_candle["l"],
                            "body_high": max(ob_candle["o"], ob_candle["c"]),
                            "body_low":  min(ob_candle["o"], ob_candle["c"]),
                            "impulse_pct": move * 100,
                            "mitigated": False,
                        })
                        i += 3
                        continue

        elif ob_candle["c"] > ob_candle["o"]:  # alcista -> posible OB bajista
            if all(candles[i + j]["c"] < candles[i + j]["o"] for j in range(1, 4)):
                move = (ob_candle["c"] - candles[i + 3]["c"]) / ob_candle["c"]
                if move > MIN_IMPULSE:
                    if i == 0 or candles[i - 1]["c"] <= candles[i - 1]["o"]:
                        results.append({
                            "type": "bearish",
                            "idx": i,
                            "high": ob_candle["h"],
                            "low":  ob_candle["l"],
                            "body_high": max(ob_candle["o"], ob_candle["c"]),
                            "body_low":  min(ob_candle["o"], ob_candle["c"]),
                            "impulse_pct": move * 100,
                            "mitigated": False,
                        })
                        i += 3
                        continue
        i += 1

    # Marcar OBs mitigados (el precio volvio al cuerpo de la OB)
    for ob in results:
        bh, bl = ob["body_high"], ob["body_low"]
        for c in candles[ob["idx"] + 1:]:
            if c["l"] <= bh and c["h"] >= bl:
                ob["mitigated"] = True
                break

    return results


# ── Market Structure (Swing Points) ──
def find_swing_points(candles, left=None, right=None, max_lookback=None):
    """Swing highs/lows de ICT. Requiere al menos `left` velas mas altas/bajas
    a cada lado para confirmar el punto de giro.

    Devuelve (swing_highs, swing_lows) ordenados por indice.
    """
    left = left or SWING_LOOKBACK
    right = right or SWING_LOOKBACK
    n = len(candles)
    highs, lows = [], []
    start = (max_lookback or 0) + left
    end = n - right

    for i in range(start, end):
        hi = candles[i]["h"]
        lo = candles[i]["l"]

        is_high = all(hi > candles[j]["h"] for j in range(i - left, i)) and \
                  all(hi > candles[j]["h"] for j in range(i + 1, i + right + 1))
        is_low  = all(lo < candles[j]["l"] for j in range(i - left, i)) and \
                  all(lo < candles[j]["l"] for j in range(i + 1, i + right + 1))

        if is_high and is_low:
            # Si es ambas, priorizar segun el rango mayor
            rng_high = hi - candles[i]["l"]
            rng_low  = candles[i]["h"] - lo
            if rng_high >= rng_low:
                highs.append({"idx": i, "price": hi})
            else:
                lows.append({"idx": i, "price": lo})
        elif is_high:
            highs.append({"idx": i, "price": hi})
        elif is_low:
            lows.append({"idx": i, "price": lo})

    return highs, lows


# ── CHoCH / MSS (Change of Character / Market Structure Shift) ──
def detect_choch(candles, swing_highs, swing_lows, lookahead=None):
    """Change of Character ICT — corregido.

    1. Toma los ULTIMOS 2 swing highs y 2 swing lows.
    2. Determina la estructura:
       - Alcista: HH (sh[1] > sh[0]) y HL (sl[1] > sl[0])
       - Bajista: LH (sh[1] < sh[0]) y LL (sl[1] < sl[0])
    3. CHoCH ocurre cuando se rompe el ultimo nivel de la estructura:
       - Bajista (rompe tendencia alcista): precio CIERRA debajo del ultimo HL
       - Alcista (rompe tendencia bajista): precio CIERRA encima del ultimo LH

    Usa el cierre en vez del high/low para evitar que una sombra momentanea
    active un falso CHoCH.
    """
    lookahead = lookahead or CHoCH_LOOKAHEAD
    n = len(candles)
    results = []

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return results

    sh = swing_highs[-2:]  # ultimos 2 swing highs
    sl = swing_lows[-2:]   # ultimos 2 swing lows

    is_uptrend   = sh[1]["price"] > sh[0]["price"] and sl[1]["price"] > sl[0]["price"]
    is_downtrend = sh[1]["price"] < sh[0]["price"] and sl[1]["price"] < sl[0]["price"]

    # Bearish CHoCH: tendencia alcista, se pierde el ultimo HL (cierre debajo)
    if is_uptrend:
        hl_level, hl_idx = sl[-1]["price"], sl[-1]["idx"]
        for i in range(hl_idx + 1, min(hl_idx + lookahead, n)):
            if candles[i]["c"] < hl_level:
                results.append({
                    "type": "bearish_choch",
                    "idx": i,
                    "level": hl_level,
                    "direction": "down",
                })
                break

    # Bullish CHoCH: tendencia bajista, se pierde el ultimo LH (cierre encima)
    if is_downtrend:
        lh_level, lh_idx = sh[-1]["price"], sh[-1]["idx"]
        for i in range(lh_idx + 1, min(lh_idx + lookahead, n)):
            if candles[i]["c"] > lh_level:
                results.append({
                    "type": "bullish_choch",
                    "idx": i,
                    "level": lh_level,
                    "direction": "up",
                })
                break

    return results


# ── Liquidez (Buyside / Sellside) ──
def detect_liquidity(swing_highs, swing_lows, max_points=4):
    """Niveles de liquidez ICT.

    - Buyside liquidity: encima de swing highs relevantes (max 4)
    - Sellside liquidity: debajo de swing lows relevantes (max 4)

    Solo se muestran niveles donde hayan AL MENOS 2 swing points cerca
    (formando un "double top/bottom" de liquidez) o el swing mas reciente.
    """
    # Agrupar swing highs cercanos (dentro del 0.1% de distancia)
    def cluster(swings, price_key, threshold=0.001):
        if not swings:
            return []
        clustered = []
        used = set()
        for i, s1 in enumerate(swings):
            if i in used:
                continue
            group = [s1]
            used.add(i)
            for j, s2 in enumerate(swings):
                if j in used or j == i:
                    continue
                if abs(s2[price_key] - s1[price_key]) / max(s1[price_key], 0.0001) < threshold:
                    group.append(s2)
                    used.add(j)
            # Solo mostrar si hay cluster (2+) o es el mas reciente
            if len(group) >= 2 or i == len(swings) - 1:
                avg_price = sum(s[price_key] for s in group) / len(group)
                clustered.append({
                    "idx": max(s["idx"] for s in group),
                    "price": avg_price,
                    "strength": len(group),
                })
        return clustered[-max_points:]

    buyside  = cluster(swing_highs, "price") if swing_highs else []
    sellside = cluster(swing_lows,  "price") if swing_lows else []

    return {"buyside": buyside, "sellside": sellside}


# ── Premium / Discount ──
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


# ── OTE (Optimal Trade Entry) ──
def calc_ote(high, low, kind="bullish"):
    """Zona OTE ICT: Fibonacci 0.618 - 0.79 de un movimiento.

    Para entradas alcistas se usa el retroceso de un movimiento bajista,
    y viceversa.
    """
    if high == low:
        return None
    fib618 = low + (high - low) * 0.618
    fib79  = low + (high - low) * 0.79
    return {"high": max(fib618, fib79), "low": min(fib618, fib79)}


# ── Detector completo ──
def detect_all(candles):
    """Ejecuta todas las detecciones ICT con parametros estrictos.

    Retorna dict con todas las detecciones o None si no hay suficientes datos.
    """
    if not candles or len(candles) < 20:
        return {}

    swing_highs, swing_lows = find_swing_points(candles)
    fvgs    = detect_fvgs(candles)
    obs     = detect_order_blocks(candles)
    choch   = detect_choch(candles, swing_highs, swing_lows)
    liq     = detect_liquidity(swing_highs, swing_lows)
    last_60 = candles[-60:] if len(candles) >= 60 else candles
    pd      = calc_pd_array(max(c["h"] for c in last_60), min(c["l"] for c in last_60))

    # OTE basado en el rango de los ultimos 2 swing points
    ote = None
    if swing_highs and swing_lows:
        last_sh = swing_highs[-1]
        last_sl = swing_lows[-1]
        move_high = max(last_sh["price"], last_sl["price"])
        move_low  = min(last_sh["price"], last_sl["price"])
        if move_high != move_low:
            ote = calc_ote(move_high, move_low, "bullish")

    return {
        "fvgs":         fvgs,
        "order_blocks": obs,
        "swing_highs":  swing_highs,
        "swing_lows":   swing_lows,
        "choch":        choch,
        "liquidity":    liq,
        "pd_array":     pd,
        "ote":          ote,
    }
