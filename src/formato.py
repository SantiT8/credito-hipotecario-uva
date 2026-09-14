"""Regla única de formato de números (español de Argentina) para notebooks, documentos, dashboard y deck.

  Cantidades:  menos de 1 millón → "146 mil"      · 1 millón o más → "1,4 millones"
  Montos:      "$ 1,2 millones" · "USD 111 mil"   · "$ 2 billones" (billón = un millón de millones)
  Porcentajes: "12,4%"

El dashboard replica estas mismas funciones en JavaScript (dashboard/index.html, bloque "formato").
"""


def _num(x: float, decimales: int = 0) -> str:
    texto = f"{x:,.{decimales}f}"
    return texto.replace(",", " ").replace(".", ",").replace(" ", ".")


def _escala(x: float, divisor: float, singular: str, plural: str) -> str:
    v = round(x / divisor, 1)
    if v == int(v):
        return f"{int(v)} {singular if abs(v) == 1 else plural}"
    return f"{_num(v, 1)} {plural}"


def fmt_cantidad(x: float) -> str:
    """146 mil · 1,4 millones · 36 (menos de mil se muestra entero)."""
    a = abs(x)
    if a < 1_000:
        return _num(round(x))
    if round(a / 1e3) < 1_000:
        return f"{_num(round(x / 1e3))} mil"
    if round(a / 1e6, 1) < 1_000:
        return _escala(x, 1e6, "millón", "millones")
    if round(a / 1e9, 1) < 1_000:
        return _escala(x, 1e9, "mil millones", "mil millones")
    return _escala(x, 1e12, "billón", "billones")


def fmt_hogares(x: float) -> str:
    return f"{fmt_cantidad(x)} {'hogar' if round(x) == 1 else 'hogares'}"


def fmt_monto(x: float, moneda: str = "$", exacto: bool = False) -> str:
    """$ 1,2 millones · USD 111 mil. exacto=True para valores chicos que no deben redondearse (USD 2.471 por m²)."""
    return f"{moneda} {_num(round(x)) if exacto else fmt_cantidad(x)}"


def fmt_pct(x: float, decimales: int = 1) -> str:
    return f"{_num(x, decimales)}%"


def fmt_decimal(x: float, decimales: int = 1) -> str:
    return _num(x, decimales)


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fmt_mes(fecha) -> str:
    """Fecha → "nov-17" (sin depender del idioma del sistema)."""
    return f"{MESES[fecha.month - 1]}-{fecha.year % 100:02d}"


if __name__ == "__main__":
    for v in [36, 999, 1_000, 18_164, 146_250, 154_793, 999_499, 999_600, 1_000_000, 1_244_791, 6_004_001, 2_000_000_000_000]:
        print(v, "→", fmt_cantidad(v), "|", fmt_monto(v))
    print(fmt_monto(2471, "USD", exacto=True), fmt_pct(12.4353), fmt_hogares(1))
