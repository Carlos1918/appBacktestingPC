"""Persistencia del journal de operaciones en un archivo JSON local."""
import json
from pathlib import Path

STORE_DIR = Path.home() / "BacktestICT"
STORE_FILE = STORE_DIR / "journal.json"


def load_trades():
    try:
        if STORE_FILE.exists():
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_trades(trades):
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = STORE_FILE.with_suffix(".json.tmp")
    # Escribe primero a un archivo temporal y luego renombra: si la app se cierra
    # o crashea a mitad de la escritura, journal.json nunca queda a medio escribir.
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)
    tmp_file.replace(STORE_FILE)
