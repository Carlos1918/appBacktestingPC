"""Formateo de precios.

Usa los dígitos decimales reales del símbolo cuando se conocen (consultados a MT5
vía `mt5_data.get_symbol_digits`). Si no se conocen —por ejemplo con datos
cargados desde un CSV manual, donde no hay forma de preguntarle a MT5— cae a la
heurística por magnitud que ya usaba la versión anterior, para no romper ese caso.
"""


def format_price(value, digits=None):
    if digits is not None:
        return f"{value:.{digits}f}"
    return f"{value:.2f}" if abs(value) > 100 else f"{value:.5f}"
