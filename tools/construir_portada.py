"""Portada del proyecto para el portfolio: 1920×1080 WebP (< 110 KB), esquina inferior izquierda libre.

Uso:  .venv\\Scripts\\python.exe tools\\construir_portada.py
Salida: deck/portada-credito-hipotecario-uva.webp
"""
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from formato import fmt_cantidad, fmt_pct  # noqa: E402

K = json.loads((ROOT / "data" / "processed" / "resultados" / "kpis.json").read_text(encoding="utf-8"))
SALIDA = ROOT / "deck" / "portada-credito-hipotecario-uva.webp"
BG, INK, INK2, MUTED, LINE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, RAMPA = "#2a78d6", ["#86b6ef", "#5598e7", "#3987e5", "#256abf", "#184f95"]


def main() -> None:
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
    fig.text(0.05, 0.86, "CASO DE ANÁLISIS DE DATOS · CRÉDITO Y VIVIENDA", fontsize=20, color=BLUE, fontweight="bold")
    fig.text(0.05, 0.62, "¿Quién puede pagar hoy\nun crédito hipotecario UVA?", fontsize=46, color=INK, fontweight="bold", linespacing=1.08, va="bottom")
    b = K["base"]
    fig.text(0.05, 0.50, f"1 de cada {round(100 / b['elegibles_pct'])}", fontsize=68, color=BLUE, fontweight="bold", va="center")
    fig.text(0.05, 0.415, "hogares que alquilan podría tomarlo hoy", fontsize=26, color=INK2, va="center")

    ax = fig.add_axes([0.665, 0.24, 0.30, 0.54], facecolor=BG)
    etapas = ["Inquilinos", "Pagan la cuota", "Juntan el anticipo", "Ingreso demostrable", "Cumplen la edad"]
    valores = [e["hogares"] for e in b["embudo"]]
    y = list(range(len(valores)))[::-1]
    ax.barh(y, valores, color=RAMPA, height=0.62)
    for yi, v, e in zip(y, valores, b["embudo"]):
        ax.text(v + valores[0] * 0.015, yi, f"{fmt_cantidad(v)} · {fmt_pct(e['pct_del_total'])}", va="center", fontsize=19, color=INK2)
    ax.set_yticks(y, etapas, fontsize=19, color=INK2)
    ax.set_xlim(0, valores[0] * 1.6)
    for lado in ["top", "right", "bottom"]:
        ax.spines[lado].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([])
    fig.text(0.545, 0.84, "Embudo de elegibilidad · CABA, GBA y Gran Córdoba", fontsize=20, color=INK, fontweight="bold")
    pk = K["producto_propuesto"]
    fig.text(0.545, 0.14, f"Producto propuesto: {fmt_cantidad(pk['elegibles_hogares'])}  ·  con independientes: {fmt_cantidad(pk['con_independientes_hogares'])}",
             fontsize=19, color=INK2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, metadata={"Software": None})
    plt.close(fig)
    im = Image.open(buf).convert("RGB").resize((1920, 1080))
    for calidad in (88, 82, 76, 70, 64, 58):
        salida = io.BytesIO()
        im.save(salida, "WEBP", quality=calidad, method=6)
        if salida.tell() < 110_000:
            break
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_bytes(salida.getvalue())
    print(f"  ✓ {SALIDA.relative_to(ROOT)} ({salida.tell() / 1024:.0f} KB, calidad {calidad})")


if __name__ == "__main__":
    main()
