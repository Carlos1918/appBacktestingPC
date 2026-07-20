"""Estadísticas avanzadas del journal — lógica de dominio pura (sin Qt), igual
que trading_account.py, para que sea fácil de cubrir con tests unitarios.
"""


def compute_advanced_stats(trades):
    """Recibe la lista de trades tal como la guarda journal_store (más reciente
    primero) y devuelve profit factor, Sharpe por-trade, rachas consecutivas y
    mejor/peor R. Devuelve ceros si no hay operaciones."""
    if not trades:
        return {
            "profit_factor": 0.0, "sharpe": 0.0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "best_r": 0.0, "worst_r": 0.0,
        }

    gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
    gross_loss = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0)  # <= 0
    if gross_loss != 0:
        profit_factor = gross_profit / abs(gross_loss)
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    r_values = [t["r"] for t in trades]
    n = len(r_values)
    mean_r = sum(r_values) / n
    variance = sum((r - mean_r) ** 2 for r in r_values) / n
    std_r = variance ** 0.5
    sharpe = (mean_r / std_r) if std_r > 0 else 0.0

    # journal_store guarda el más reciente primero (insert(0, ...)) -- para
    # rachas hace falta el orden cronológico real.
    chrono = list(reversed(trades))
    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for t in chrono:
        if t["result"] == "Ganada":
            cur_win += 1
            cur_loss = 0
        elif t["result"] == "Perdida":
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)

    return {
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "best_r": max(r_values),
        "worst_r": min(r_values),
    }
