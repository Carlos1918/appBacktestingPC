"""Cuenta simulada: balance, equity y cálculo de P&L/R de las operaciones.

Se separa de la ventana principal porque es lógica de dominio pura (sin Qt) — y
por lo tanto la más fácil, y la más importante, de cubrir con tests unitarios sin
tener que levantar una QApplication.
"""
from . import mt5_data


class TradingAccount:
    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self._contract_size_cache = {}

    def get_contract_size(self, symbol):
        if symbol not in self._contract_size_cache:
            try:
                self._contract_size_cache[symbol] = mt5_data.get_contract_size(symbol)
            except Exception:
                self._contract_size_cache[symbol] = 100.0
        return self._contract_size_cache[symbol]

    def reset(self, balance):
        self.balance = balance

    def apply_pnl(self, pnl):
        self.balance += pnl

    @staticmethod
    def compute_r(trade, exit_price):
        """R-múltiplo del resultado. Si el SL coincide exactamente con la entrada
        (riesgo 0), devuelve 0 en vez de dividir por cero."""
        risk = (trade["entry"] - trade["sl"]) if trade["dir"] == "buy" else (trade["sl"] - trade["entry"])
        reward = (exit_price - trade["entry"]) if trade["dir"] == "buy" else (trade["entry"] - exit_price)
        return reward / risk if risk != 0 else 0

    @staticmethod
    def compute_pnl(trade, exit_price):
        """P&L en dinero. Aproximado (no incluye spread, comisión ni conversión de
        divisa de la cuenta) — pensado como referencia adicional al R-múltiplo."""
        diff = (exit_price - trade["entry"]) if trade["dir"] == "buy" else (trade["entry"] - exit_price)
        return diff * trade.get("volume", 0.1) * trade.get("contract_size", 100.0)
