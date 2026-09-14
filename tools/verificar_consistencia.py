"""Verifica que las cifras clave de kpis.json aparezcan igual en todos los productos publicados.

Uso:  python tools/verificar_consistencia.py

Revisa el Resumen en simple, el Documento metodológico, la presentación, el carrusel, el README, la recomendación,
los hallazgos y los datos embebidos del dashboard. Sale con código 1 si falta alguna cifra.
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from formato import fmt_cantidad, fmt_pct  # noqa: E402

K = json.loads((ROOT / "data" / "processed" / "resultados" / "kpis.json").read_text(encoding="utf-8"))


def texto_pdf(ruta: Path) -> str:
    return " ".join((p.extract_text() or "") for p in PdfReader(str(ruta)).pages)


def normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace(" ", " "))


def main() -> int:
    b, p = K["base"], K["producto_propuesto"]
    cifras = {
        "elegibles": fmt_cantidad(b["elegibles_hogares"]),
        "% elegibles": fmt_pct(b["elegibles_pct"]),
        "1 de cada N": f"1 de cada {round(100 / b['elegibles_pct'])}",
        "propuesto": fmt_cantidad(p["elegibles_hogares"]),
        "con independientes": fmt_cantidad(p["con_independientes_hogares"]),
        "inquilinos": fmt_cantidad(K["universo"]["inquilinos"]),
    }
    productos = {
        "Resumen en simple (PDF)": texto_pdf(ROOT / "reports" / "resumen_en_simple.pdf"),
        "Documento metodológico (PDF)": texto_pdf(ROOT / "reports" / "documento_metodologico.pdf"),
        "Presentación (PDF)": texto_pdf(ROOT / "deck" / "presentacion.pdf"),
        "README": (ROOT / "README.md").read_text(encoding="utf-8"),
        "Recomendación": (ROOT / "reports" / "03_recomendacion.md").read_text(encoding="utf-8"),
        "Hallazgos": (ROOT / "reports" / "02_insights.md").read_text(encoding="utf-8"),
    }
    exigidas = {
        "Resumen en simple (PDF)": ["elegibles", "1 de cada N", "propuesto", "con independientes", "inquilinos"],
        "Documento metodológico (PDF)": list(cifras),
        "Presentación (PDF)": ["elegibles", "1 de cada N", "propuesto", "con independientes", "inquilinos"],
        "README": list(cifras),
        "Recomendación": ["elegibles", "propuesto", "con independientes"],
        "Hallazgos": list(cifras),
    }
    fallas = 0
    for producto, texto in productos.items():
        texto = normalizar(texto)
        faltan = [f"{c} ({cifras[c]})" for c in exigidas[producto] if cifras[c] not in texto]
        fallas += len(faltan)
        print(f"{'OK ' if not faltan else 'FALTA'} {producto}" + (f": {', '.join(faltan)}" if faltan else ""))

    # Dashboard: los KPI embebidos deben ser los mismos números de kpis.json
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    datos = json.loads(re.search(r"var DATOS = (\{.*?\});</script>", html, re.S).group(1).replace("<\\/", "</"))
    pares = [("elegibles_base", b["elegibles_hogares"]), ("propuesto", p["elegibles_hogares"]),
             ("propuesto_indep", p["con_independientes_hogares"]), ("inquilinos", K["universo"]["inquilinos"])]
    for clave, valor in pares:
        ok = abs(datos["kpis"][clave] - valor) < 0.5
        fallas += not ok
        print(f"{'OK ' if ok else 'FALTA'} Dashboard · {clave}: {datos['kpis'][clave]:,.0f} vs {valor:,.0f}")
    print("\nConsistencia OK" if not fallas else f"\n{fallas} diferencias")
    return int(fallas > 0)


if __name__ == "__main__":
    sys.exit(main())
