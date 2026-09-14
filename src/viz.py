"""Estilo visual único para todos los gráficos estáticos (notebooks, figuras del deck).

Paleta categórica validada para lectura con daltonismo (separación de color y contraste).
Reglas: color asignado por rol y en orden fijo, un solo eje Y, líneas de 2px,
grilla y ejes en hairline, texto siempre en tinta (nunca del color de la serie).
"""
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

from config import FIGURES
from formato import fmt_cantidad, fmt_decimal, fmt_hogares, fmt_monto, fmt_pct  # noqa: F401 (reexportadas)

# Categóricos en orden fijo (nunca ciclar)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BLUE, ORANGE, AQUA = SERIES[0], SERIES[1], SERIES[2]
# Secuencial azul (claro → oscuro) para rampas ordinales: arrancar en step 250 sobre fondo claro
BLUE_RAMP = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]
# Tinta y chrome
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
# Énfasis: gris para "el resto" cuando la historia es una sola serie
CONTEXT_GRAY = "#c3c2b7"


def apply_style() -> None:
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.titlepad": 28,
        "axes.edgecolor": BASELINE, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
        "axes.axisbelow": True,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "ytick.left": False, "xtick.major.size": 0,
        "lines.linewidth": 2, "lines.solid_capstyle": "round",
        "axes.prop_cycle": mpl.cycler(color=SERIES),
        "legend.frameon": False, "legend.fontsize": 9, "legend.labelcolor": INK_2,
        "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight",
    })


def subtitle(ax, text: str) -> None:
    """Subtítulo en tinta secundaria debajo del título (la bajada del gráfico)."""
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK_2, fontsize=9, va="bottom")


def titulo_figura(fig, texto: str) -> None:
    """Título general de una figura con varios paneles, siempre por encima de títulos y bajadas de cada panel."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    textos = [t for ax in fig.axes for t in [ax.title, ax._left_title, ax._right_title, *ax.texts] if t.get_text()]
    tope = max(t.get_window_extent(r).y1 for t in textos) / fig.bbox.height
    fig.text(0.01, tope + 0.12 / fig.get_figheight(), texto, fontsize=12.5, fontweight="semibold", color=INK, ha="left", va="bottom")


def source(fig, text: str) -> None:
    fig.text(0.01, -0.02, f"Fuente: {text}", color=MUTED, fontsize=8, ha="left", va="top")


def save(fig, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    # Sin metadatos de software ni fecha en los archivos publicados
    fig.savefig(FIGURES / f"{name}.png", metadata={"Software": None})
    fig.savefig(FIGURES / f"{name}.svg", metadata={"Creator": None, "Date": None})


# Formateadores de ejes con la regla única de números (formato.py)
EJE_CANTIDAD = mtick.FuncFormatter(lambda v, _: fmt_cantidad(v) if v else "0")
EJE_PCT = mtick.FuncFormatter(lambda v, _: fmt_pct(v, 0 if abs(v - round(v)) < 1e-9 else 1))
EJE_DECIMAL = mtick.FuncFormatter(lambda v, _: fmt_decimal(v, 1))
RED = "#e34948"  # solo para "resta" en gráficos de cambio (no es un color de serie)


apply_style()
plt.rcParams["axes.unicode_minus"] = False
