"""Guardado y carga de sesiones completas de backtest.

Permite cerrar la app y retomar exactamente donde se quedó:
símbolo, timeframe, posición del replay, dibujos, operación
abierta, configuración ICT/EMA y saldo de la cuenta.
"""
import json
import os
from pathlib import Path

STORE_DIR = Path.home() / "BacktestICT"
SESSIONS_DIR = STORE_DIR / "sessions"

def ensure_dirs():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

def list_sessions():
    ensure_dirs()
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            name = data.get("name", f.stem)
            sessions.append({
                "path": str(f),
                "name": name,
                "symbol": data.get("symbol", "?"),
                "tf": data.get("tf", "?"),
                "trades": data.get("total_trades", 0),
                "date": data.get("saved_at", ""),
            })
        except Exception:
            sessions.append({"path": str(f), "name": f.stem, "symbol": "?", "tf": "?", "trades": 0, "date": ""})
    return sessions

def save_session(name, state):
    ensure_dirs()
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()
    if not safe_name:
        safe_name = "sesion"
    path = SESSIONS_DIR / f"{safe_name}.json"
    state["name"] = name
    state["saved_at"] = state.get("saved_at", "")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return str(path)

def load_session(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def delete_session(path):
    if os.path.exists(path):
        os.remove(path)
