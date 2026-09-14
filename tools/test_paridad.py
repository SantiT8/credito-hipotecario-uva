"""Test de paridad: el simulador del dashboard (dashboard/motor.js) da los mismos resultados que src/affordability.py.

Uso:  .venv\\Scripts\\python.exe tools\\test_paridad.py

1. Paridad exacta: Python y JavaScript evalúan el mismo subconjunto publicado en dashboard_data.json.
2. Fidelidad: el subconjunto publicado (ingresos redondeados a miles) reproduce las cifras de kpis.json.
Requiere Node.js.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from affordability import Producto, evaluar  # noqa: E402

DATOS = ROOT / "data" / "processed" / "resultados" / "dashboard_data.json"
KPIS = ROOT / "data" / "processed" / "resultados" / "kpis.json"
ESCENARIOS = {
    "base": {},
    "propuesto": {"plazo_anios": 30, "ltv": 0.80},
    "propuesto_independientes": {"plazo_anios": 30, "ltv": 0.80, "acepta_independientes": True},
    "tasa_baja_precio_menor": {"tna": 0.055, "factor_precio": 0.8},
    "m2_fijo_45_tope_30": {"m2_fijo": 45, "tope_cuota_ingreso": 0.30},
    "anticipo_24_edad_75": {"meses_ingreso_anticipo": 24, "edad_max_fin_credito": 75},
}
ZONAS = ["CABA", "GBA Norte", "GBA Oeste", "GBA Sur", "Gran Córdoba", "Total"]


def datos_python(d: dict) -> tuple[pd.DataFrame, dict]:
    h = pd.DataFrame(d["hogares"], columns=d["hogares_campos"])
    h["mercado"] = h.mercado.map(dict(enumerate(d["mercado"]["nombres"])))
    h = h.rename(columns={"formal": "hogar_formal", "independiente": "jefe_o_conyuge_indep_registrado",
                          "edad_jefe": "jefe_edad", "ingreso_ago26": "ingreso"})
    gba = pd.DataFrame(d["mercado"]["gba_partidos"]).rename(columns={"peso_gba": "peso_en_gba", "peso_corredor": "peso_en_corredor"})
    m = {"tc": d["mercado"]["tc"], "uva": d["mercado"]["uva"], "usd_m2": d["mercado"]["usd_m2"], "gba_partidos": gba}
    return h, m


def resultados_python(h: pd.DataFrame, m: dict, cambios: dict) -> dict:
    ev = evaluar(h, m, Producto().con(**cambios))
    ev["zona"] = ev.apply(lambda r: f"GBA {r.corredor}" if r.mercado == "Partidos del GBA" else r.mercado, axis=1)
    out = {z: float(g.peso[g.elegible].sum()) for z, g in ev.groupby("zona")}
    out["Total"] = float(ev.peso[ev.elegible].sum())
    return out


def resultados_js(escenarios: dict) -> dict:
    base = {"tna": 0.075, "plazo_anios": 20, "ltv": 0.75, "tope_cuota_ingreso": 0.25, "gastos_compra": 0.07,
            "tope_prestamo_uva": 150000, "meses_ingreso_anticipo": 12, "edad_max_fin_credito": 85,
            "acepta_independientes": False, "factor_precio": 1, "m2_fijo": None}
    script = f"""
const Motor = require({json.dumps(str(ROOT / 'dashboard' / 'motor.js'))});
const datos = require({json.dumps(str(DATOS))});
const base = {json.dumps(base)};
const escenarios = {json.dumps(escenarios)};
const out = {{}};
for (const [nombre, cambios] of Object.entries(escenarios)) {{
  const r = Motor.evaluar(datos, Object.assign({{}}, base, cambios));
  out[nombre] = Object.fromEntries(Object.entries(r).map(([z, e]) => [z, e[4]]));
}}
console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(script)
        ruta = f.name
    salida = subprocess.run(["node", ruta], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    Path(ruta).unlink()
    return json.loads(salida)


def main() -> int:
    d = json.loads(DATOS.read_text(encoding="utf-8"))
    k = json.loads(KPIS.read_text(encoding="utf-8"))
    h, m = datos_python(d)
    js = resultados_js(ESCENARIOS)
    fallas = 0
    print(f"{'escenario':28} {'zona':13} {'python':>12} {'javascript':>12} {'dif. rel.':>10}")
    for nombre, cambios in ESCENARIOS.items():
        py = resultados_python(h, m, cambios)
        for z in ZONAS:
            a, b = py.get(z, 0.0), js[nombre].get(z, 0.0)
            rel = abs(a - b) / max(a, 1)
            fallas += rel > 1e-9
            print(f"{nombre:28} {z:13} {a:12,.1f} {b:12,.1f} {rel:10.2e}")
    # Fidelidad del subconjunto publicado frente al cálculo con datos completos
    completos = {"base": k["base"]["elegibles_hogares"], "propuesto": k["producto_propuesto"]["elegibles_hogares"],
                 "propuesto_independientes": k["producto_propuesto"]["con_independientes_hogares"]}
    print()
    for nombre, valor in completos.items():
        rel = abs(js[nombre]["Total"] - valor) / valor
        fallas += rel > 0.005
        print(f"Fidelidad {nombre:26} kpis {valor:12,.0f} · dashboard {js[nombre]['Total']:12,.0f} · dif. {100 * rel:.3f}%")
    print("\nOK: paridad exacta y fidelidad < 0,5%" if not fallas else f"\nFALLAS: {fallas}")
    return int(fallas > 0)


if __name__ == "__main__":
    sys.exit(main())
