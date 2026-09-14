"""Genera el Documento metodológico y el Resumen en simple (HTML autocontenido + PDF).

Uso:  .venv\\Scripts\\python.exe src\\build_docs.py

Todas las cifras salen de data/processed/evidencia, de kpis.json y de la base DuckDB: los documentos
no pueden contradecir al análisis. Números con la regla única de formato (src/formato.py).
"""
import base64
import json
import subprocess
from datetime import date
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader

import viz
from affordability import factor_cuota
from config import BASE, DB_PATH, FECHA_CORTE, FIGURES, PROCESSED, RAW, ROOT
from formato import fmt_cantidad as C, fmt_decimal as D, fmt_mes, fmt_monto as M, fmt_pct as P

EV = PROCESSED / "evidencia"
RESULTADOS = PROCESSED / "resultados"
TEMPLATES = ROOT / "reports" / "templates"
REPORTS = ROOT / "reports"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
AUTOR = "Santiago Trotta"
VERSION = "1.0"


def ev(carpeta: str, nombre: str) -> pd.DataFrame:
    return pd.read_csv(EV / carpeta / f"{nombre}.csv")


def mes(texto: str) -> str:
    """"2026-05" → "may-26"."""
    return fmt_mes(pd.Timestamp(f"{texto}-01"))


def exacto(x) -> str:
    """Conteos exactos (tamaños de muestra, filas): 13.175."""
    return f"{x:,.0f}".replace(",", ".")


def data_uri(path: Path) -> str:
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def wmedian(x, w) -> float:
    x, w = np.asarray(x, float), np.asarray(w, float)
    o = np.argsort(x)
    x, w = x[o], w[o]
    return float(x[np.searchsorted(np.cumsum(w), w.sum() / 2)])


# ---------------------------------------------------------------------------
# Figuras propias del documento
# ---------------------------------------------------------------------------
def fig_ponderar(con) -> tuple[Path, dict]:
    df = con.execute("""
        SELECT CASE WHEN II7 = '3' THEN 'Inquilinos' ELSE 'Propietarios' END AS grupo,
               CAST(ITF AS DOUBLE) AS itf, CAST(PONDERA AS DOUBLE) AS pondera, CAST(PONDIH AS DOUBLE) AS pondih
        FROM stg_eph_hogar
        WHERE AGLOMERADO IN ('32','33','13') AND ANO4 = '2026' AND TRIMESTRE = '1' AND II7 IN ('1','2','3')
    """).df()
    grupos = ["Inquilinos", "Propietarios"]
    ingenua = [wmedian(df[df.grupo == g].itf, df[df.grupo == g].pondera) for g in grupos]
    correcta = [wmedian(df[(df.grupo == g) & (df.pondih > 0)].itf, df[(df.grupo == g) & (df.pondih > 0)].pondih) for g in grupos]

    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    y = np.arange(len(grupos))
    h = 0.34
    b1 = ax.barh(y + h / 2 + 0.02, ingenua, height=h, color=viz.CONTEXT_GRAY, label="Cálculo ingenuo (cuenta como $ 0 a quien no respondió)")
    b2 = ax.barh(y - h / 2 - 0.02, correcta, height=h, color=viz.BLUE, label="Cálculo correcto (ponderador de ingresos del INDEC)")
    ax.set_yticks(y, grupos)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: M(v) if v else "$ 0"))
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_width() * 1.01, b.get_y() + b.get_height() / 2, M(b.get_width()), va="center", fontsize=8.5, color=viz.INK_2)
    ax.set_xlim(0, max(correcta) * 1.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=1, fontsize=8.5)
    ax.set_title("Si no se pondera bien, el ingreso típico sale mucho más bajo")
    viz.subtitle(ax, "Mediana del ingreso total familiar mensual · CABA, GBA y Gran Córdoba · 1T-2026 · pesos corrientes")
    path = FIGURES / "doc_ponderar.svg"
    fig.savefig(path, metadata={"Creator": None, "Date": None})
    plt.close(fig)
    return path, {"ingenua_inq": ingenua[0], "correcta_inq": correcta[0]}


def fig_no_respuesta(con) -> Path:
    df = con.execute("""
        SELECT mercado, 100.0 * sum(pondera_ajust) FILTER (WHERE NOT ingreso_declarado) / sum(pondera_ajust) AS pct_nr
        FROM hogares_eph GROUP BY 1 ORDER BY 2
    """).df()
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    bars = ax.barh(df.mercado, df.pct_nr, color=viz.BLUE, height=0.55)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(viz.EJE_PCT)
    ax.set_xlim(0, df.pct_nr.max() * 1.2)
    for b, v in zip(bars, df.pct_nr):
        ax.text(v + 0.8, b.get_y() + b.get_height() / 2, P(v), va="center", fontsize=9, color=viz.INK_2)
    ax.set_title("En el GBA y CABA, casi 4 de cada 10 hogares no declaran su ingreso")
    viz.subtitle(ax, "Hogares sin ingreso declarado sobre el total (ponderado) · 2T-2025 a 1T-2026")
    path = FIGURES / "doc_no_respuesta_mercado.svg"
    fig.savefig(path, metadata={"Creator": None, "Date": None})
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Cifras de datos y calidad
# ---------------------------------------------------------------------------
def numeros(con, K: dict) -> dict:
    n = {}
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    n["n_archivos"] = len(manifest["files"])
    n["n_chequeos"] = len(list((EV / "02_profiling").glob("*.csv"))) + len(list((EV / "03_clean").glob("*.csv")))

    nr = ev("02_profiling", "eph_no_respuesta_ingresos")
    fila_nr = nr[nr.situacion.str.startswith("No respuesta")].iloc[0]
    n["eph_nr_pct"] = P(fila_nr.pct)
    panel = ev("02_profiling", "eph_panel_repeticiones")
    n["eph_panel_pct"] = P(panel.loc[panel.trimestres_en_que_aparece == 2, "pct"].iloc[0])

    val = ev("03_clean", "validacion_hogares_eph")
    total = val[val.mercado.isna()].iloc[0]
    n["obs_hogar_trimestre"] = exacto(total.observaciones_hogar_trimestre)
    n["hogares_distintos"] = exacto(total.hogares_distintos)
    n["hogares_expandidos"] = C(total.hogares_expandidos)
    n["mercados"] = [{"mercado": r.mercado, "obs": exacto(r.observaciones_hogar_trimestre), "hogares": C(r.hogares_expandidos),
                      "inquilinos": C(r.inquilinos_expandidos), "pct_inq": P(r.pct_inquilinos), "pct_nr": P(r.pct_sin_ingreso_declarado)}
                     for r in val[val.mercado.notna()].sort_values("hogares_expandidos", ascending=False).itertuples()]
    pool = ev("03_clean", "validacion_pool_vs_promedio_trimestral").iloc[0]
    n["pool_ok"] = abs(pool.inquilinos_pool - pool.inquilinos_promedio_trimestral) < 1
    n["pool_inquilinos"] = C(pool.inquilinos_pool)

    fac = con.execute("""
        SELECT mes AS fecha, factor_a_pesos_ago26 FROM series_mensuales
        WHERE mes IN (DATE '2025-05-01', DATE '2025-08-01', DATE '2025-11-01', DATE '2026-02-01')
        ORDER BY fecha
    """).df()
    assert fac.factor_a_pesos_ago26.is_monotonic_decreasing, "los factores de inflación deben decrecer en el tiempo"
    n["factores"] = [{"trimestre": t, "factor": D(f, 2), "ejemplo": M(1_000_000 * f)}
                     for t, f in zip(["2T-2025", "3T-2025", "4T-2025", "1T-2026"], fac.factor_a_pesos_ago26)]

    indec = ev("03_clean", "validacion_vs_indec_1t2026").iloc[0]
    n["indec"] = {"pob": D(indec.poblacion_millones_calc), "mediana": M(indec.mediana_ipcf_calc, exacto=True), "media": M(indec.media_ipcf_calc, exacto=True)}

    emb = ev("03_clean", "gcba_embudo_limpieza")
    n["gcba_crudos"] = C(emb.avisos_crudos.sum())
    n["gcba_limpios"] = C(emb.avisos_limpios.sum())
    n["gcba_pct"] = P(100 * emb.avisos_limpios.sum() / emb.avisos_crudos.sum())
    for i, col in enumerate(["r1_no_venta_depto", "r2_precio_m2_invalido", "r3_barrio_invalido", "r4_duplicados", "r5_outliers"], start=1):
        n[f"gcba_r{i}"] = C(emb[col].sum())
    dup = ev("02_profiling", "gcba_duplicados_por_anio").set_index("anio")
    n["gcba_dup_2017"] = P(dup.loc[2017, "pct_duplicados"])
    n["gcba_dup_2020"] = P(dup.loc[2020, "pct_duplicados"])
    coords = ev("02_profiling", "gcba_coordenadas_invalidas").set_index("anio")
    n["gcba_coord_2001"] = exacto(coords.loc[2001, "lat_lon_invertidas"])
    n["gcba_coord_2019"] = exacto(coords.loc[2019, "fuera_de_rango"])
    barrios = ev("02_profiling", "gcba_barrios_variantes")
    nunez = barrios[barrios.barrio_tal_cual.fillna("").str.match(r"^NU.*EZ$")]
    n["nunez"] = [{"variante": r.barrio_tal_cual, "avisos": exacto(r.avisos),
                   "anios": f"{r.primer_anio}–{r.ultimo_anio}" if r.primer_anio != r.ultimo_anio else str(r.primer_anio)} for r in nunez.itertuples()]

    ult = ev("03_clean", "validacion_series_ultimo_dato").iloc[0]
    n["uva_ultimo"] = "$ " + D(ult.uva_ultimo, 2)

    precios = ev("03_clean", "validacion_precios_gba")
    n["corredores"] = [{"corredor": r.corredor, "partidos": int(r.partidos), "sin_precio": int(r.partidos_sin_precio_propio),
                        "inquilinos": C(r.hogares_inquilinos_censo), "pct": P(r.pct_de_inquilinos_gba, 0),
                        "usd_m2": M(r.usd_m2_ponderado_inquilinos, "USD", exacto=True),
                        "rango": f"{M(r.usd_m2_min, 'USD', exacto=True)} a {M(r.usd_m2_max, 'USD', exacto=True)}"} for r in precios.itertuples()]

    comp = pd.read_csv(EV / "validacion_censo" / "comparacion_eph_censo.csv")
    n["censo"] = [{"zona": r.zona, "geo": r.geografia_censo, "hogares_censo": C(r.hogares_censo), "hogares_eph": C(r.hogares_eph) if pd.notna(r.hogares_eph) else "—",
                   "alq_censo": P(r.pct_alquilada_censo), "alq_eph": P(r.pct_alquilada_eph) if pd.notna(r.pct_alquilada_eph) else "—",
                   "dif": (D(r.dif_alquila_pp) + " pp").replace("-", "−") if pd.notna(r.dif_alquila_pp) else "—"} for r in comp.itertuples()]
    return n


# ---------------------------------------------------------------------------
# Cifras de resultados (desde kpis.json)
# ---------------------------------------------------------------------------
def resultados(K: dict) -> dict:
    b, p, h2, h4, u = K["base"], K["producto_propuesto"], K["h2"], K["h4"], K["universo"]
    cz = u["censo"]
    zonas = {r["zona"]: r for r in h4["por_zona"]}
    edades = {r["tramo_edad_jefe"]: r for r in h4["por_edad"]}
    perfil = {(r["tipo_hogar"], r["jefatura"]): r for r in K["h3"]["perfil"]}
    stress = {r["horizonte_meses"]: r for r in K["h5"]["stress_resumen"]}
    trab = {r["grupo"]: r for r in K["h7"]["por_trabajos"]}
    odds = {r["variable"]: r for r in K["logit"]["odds_ratios"]}
    qps = {r["pregunta"]: r for r in K["que_pasa_si"]}
    qle = {r["pregunta"]: r for r in K["que_lo_empeora"]}
    ind = K["h5"]["independientes"]
    vol = {r["insercion"]: r for r in K["h5"]["volatilidad"]}
    nr = K["robustez"]["no_respuesta"]
    sub = K["robustez"]["subdeclaracion"]["escenarios"]
    cob = K["robustez"]["subdeclaracion"]["cobertura"]
    hit = K["contexto_mercado"]["hitos"]
    sueldo = {r["mes"]: r for r in K["h5"]["sueldo_hitos"]}
    calor = {(r["zona"], r["m2"]): r["pct_elegible"] for r in K["h1"]["calor_zona"]}
    destino = {r["mes"]: r for r in K["contexto_mercado"]["destino_ultimo"]}
    d26 = destino[max(destino)]
    tot26 = sum(d26[c] for c in ["compra_usada", "compra_nueva", "construccion", "refaccion", "otros"])
    emb = {e["etapa"]: e for e in b["embudo"]}
    ic_c = b["pasan_cuota_ic95"]
    seg = sorted(K["segmentos"]["perfil"], key=lambda s: -s["hogares"])
    signo = lambda x: ("+" if x > 0.5 else "−" if x < -0.5 else "") + C(abs(x))

    return {
        "universo": [
            {"titulo": "Todos los hogares", "detalle": "CABA, Partidos del GBA y Gran Córdoba", "valor": u["hogares_3_mercados"], "etiqueta": C(u["hogares_3_mercados"]), "color": "#c3c2b7"},
            {"titulo": "Alquilan", "detalle": "la base de todos los porcentajes", "valor": u["inquilinos"], "etiqueta": C(u["inquilinos"]), "color": "#86b6ef"},
            {"titulo": "Pueden pagar la cuota", "detalle": "cuota hasta 25% del ingreso", "valor": b["pasan_cuota_hogares"], "etiqueta": C(b["pasan_cuota_hogares"]), "color": "#3987e5"},
            {"titulo": "Pueden sacar el crédito", "detalle": "cumplen las 4 condiciones", "valor": b["elegibles_hogares"],
             "etiqueta": f"{C(b['elegibles_hogares'])} (1 de cada {round(100 / b['elegibles_pct'])})", "color": "#184f95"}],
        "hogares": C(u["hogares_3_mercados"]), "inquilinos": C(u["inquilinos"]), "pct_inquilinos": P(u["pct_inquilinos"]),
        "propietarios": C(u["propietarios"]), "otra": C(u["otra_situacion"]),
        "obs_inq": exacto(u["observaciones_inquilinos_con_ingreso"]), "hog_inq": exacto(u["hogares_encuestados_inquilinos_con_ingreso"]),
        "inq_sin_ingreso": C(u["inquilinos_sin_ingreso_declarado"]),
        "censo_factor_min": D(cz["factor_ajuste_min"], 2), "censo_factor_max": D(cz["factor_ajuste_max"], 2),
        "censo_hog_pais": C(cz["hogares_pais_censo"]), "censo_propia_pais": P(cz["pct_propia_pais_censo"]), "censo_alq_pais": P(cz["pct_alquilada_pais_censo"]),
        "elegibles": C(b["elegibles_hogares"]), "elegibles_pct": P(b["elegibles_pct"]), "uno_de_cada": round(100 / b["elegibles_pct"]),
        "ic_inf": P(b["elegibles_ic95"][0]), "ic_sup": P(b["elegibles_ic95"][1]),
        "rango_censo": f"{C(b['elegibles_rango_censo'][0])} y {C(b['elegibles_rango_censo'][1])}",
        "cuota_pct": P(b["pasan_cuota_pct"]), "cuota_ic_inf": P(ic_c[0]), "cuota_ic_sup": P(ic_c[1]), "cuota_hog": C(b["pasan_cuota_hogares"]),
        "h1_veredicto": "En el límite" if ic_c[0] <= 20 <= ic_c[1] else ("Refutada por poco" if ic_c[0] > 20 else "Confirmada"),
        "etapas": [{"etapa": e["etapa"], "hogares": C(e["hogares"]), "pct": P(e["pct_del_total"])} for e in b["embudo"]],
        "sin_formal_pct": P(100 - emb["Ingreso demostrable"]["pct_de_etapa_anterior"], 0),
        "no_cuota": round(10 * (1 - b["pasan_cuota_pct"] / 100)),
        "ingreso_mediano_inq": M(b["ingreso_mediano_inquilinos"]), "ingreso_mediano_eleg": M(b["ingreso_mediano_elegibles"]),
        "tope_anticipo": D(h2["precio_max_ingresos_por_anticipo"]), "tope_cuota": D(h2["precio_max_ingresos_por_cuota"]),
        "fallan_ambos": P(h2["pct_fallan_ambos"], 0), "ltv_eq": P(100 * h2["ltv_equilibrio"], 0), "mediana_precio_ing": D(h2["mediana_precio_en_ingresos"], 0),
        "calor": {f"{z}_{m2}": P(calor[(z, m2)]) for z in ["Total", "CABA", "GBA Norte", "GBA Oeste", "GBA Sur", "Gran Córdoba"] for m2 in (30, 45, 60, 75, 90)},
        "zonas": {z: {"pct": P(r["pct_elegible"]), "hog": C(r["hogares_elegibles"]), "ic": f"{D(r['ic95_inf'])}–{D(r['ic95_sup'])}"} for z, r in zonas.items()},
        "p_zona": D(h4["test_zona"]["p_valor"], 2), "p_edad": D(h4["test_edad"]["p_valor"], 2),
        "edad": {e: P(r["pct_elegible"]) for e, r in edades.items()},
        "perfil": {f"{t}|{j}": {"pct": P(r["pct_elegible"]), "share": P(r["pct_de_inquilinos"], 0), "ipp": M(r["ingreso_por_persona_mediano"]),
                                "n": int(r["muestra_hogares"]), "chica": r["muestra_chica"]} for (t, j), r in perfil.items()},
        "perfil_tabla": [{"tipo": r["tipo_hogar"], "jef": r["jefatura"], "share": P(r["pct_de_inquilinos"]), "ing": M(r["ingreso_mediano"]),
                          "ipp": M(r["ingreso_por_persona_mediano"]), "formal": P(r["pct_ingreso_demostrable"], 0), "pct": P(r["pct_elegible"]),
                          "ic": f"{D(r['ic95_inf'])}–{D(r['ic95_sup'])}", "n": int(r["muestra_hogares"]), "chica": r["muestra_chica"]}
                         for r in K["h3"]["perfil"] if r["agrupacion"] == "tipo_hogar × jefatura"],
        "or": {k: D(v["odds_ratio"]) for k, v in odds.items()},
        "or_mujer_ic": f"{D(odds['jefatura_mujer']['or_ic95_inf'], 2)}–{D(odds['jefatura_mujer']['or_ic95_sup'], 2)}",
        "auc": D(K["logit"]["info"]["auc_ponderado"], 2), "n_logit": exacto(K["logit"]["info"]["n_observaciones"]), "hog_logit": exacto(K["logit"]["info"]["n_hogares"]),
        "qps": {q: {"dif": signo(r["diferencia"]), "pct": signo(r["diferencia_pct"]).replace(" mil", "") + "%"} for q, r in qps.items()},
        "qps_lista": [{"pregunta": r["pregunta"], "dif": signo(r["diferencia"]), "por_que": r["por_que"]} for r in sorted(K["que_pasa_si"], key=lambda r: -r["diferencia"])],
        "qle_lista": [{"pregunta": r["pregunta"], "dif": signo(r["diferencia"])} for r in sorted(K["que_lo_empeora"], key=lambda r: r["diferencia"])],
        "prop": C(p["elegibles_hogares"]), "prop_pct": P(p["elegibles_pct"]), "prop_delta": f"+{P(p['delta_vs_base_pct'], 0)}",
        "prop_indep": C(p["con_independientes_hogares"]), "prop_indep_delta": f"+{P(p['con_independientes_delta_vs_base_pct'], 0)}",
        "ind": {"con": C(ind["inquilinos_con_independiente_registrado"]), "solo": C(ind["inquilinos_solo_independiente_sin_asalariado_formal"]),
                "pagan": C(ind["de_ellos_pasan_cuota_y_anticipo"]), "suman": C(ind["hogares_que_se_suman"]),
                "ingreso": M(ind["ingreso_mediano_de_los_que_se_suman"]), "eleg_con": C(ind["elegibles_aceptando_independientes"])},
        "vol": {k: {"cambio": P(v["cambio_absoluto_mediano_pct"], 0), "cae": P(v["pct_cae_mas_20"], 0), "n": exacto(v["muestra_hogares"])} for k, v in vol.items()},
        "stress24": P(stress[24]["peor_cuota_ingreso_pct"]), "stress24_sobre30": P(stress[24]["pct_ventanas_sobre_30"], 0),
        "sueldo": {"bruto": M(K["h5"]["sueldo_ultimo"]["bruto"]), "usd": M(K["h5"]["sueldo_ultimo"]["usd_bna"], "USD", exacto=True),
                   "real": M(K["h5"]["sueldo_ultimo"]["real_ago26"]), "mes": mes(K["h5"]["sueldo_ultimo"]["mes"]),
                   "usd17": M(sueldo["2017-11"]["sueldo_usd_bna"], "USD", exacto=True), "usd19": M(sueldo["2019-11"]["sueldo_usd_bna"], "USD", exacto=True),
                   "real17": M(sueldo["2017-11"]["sueldo_real_ago26"])},
        "trab": {g: {"pct": P(r["pct_elegible"]), "share": P(r["pct_de_inquilinos"], 0), "formal": P(r["pct_con_ingreso_demostrable"], 0),
                     "pasan": P(r["pct_pasan_cuota_y_anticipo"])} for g, r in trab.items()},
        "solo_titulares": P(abs(K["h7"]["solo_titulares"]["diferencia_pct"]), 0),
        "nr": {"pct": P(nr["pct_elegible_imputacion"]["estimacion"]), "ic": f"{D(nr['pct_elegible_imputacion']['ic95_inf'])}–{D(nr['pct_elegible_imputacion']['ic95_sup'])}",
               "share": P(nr["pct_inquilinos_sin_ingreso_declarado"], 0), "error": D(nr["validacion"]["error_absoluto_medio_pp"]),
               "hog": C(nr["hogares_elegibles_imputacion"])},
        "sub": {"mediana": P(sub[1]["pct_elegible"]), "promedio": P(sub[2]["pct_elegible"]), "f_med": D(sub[1]["factor_sueldo_formal"], 2),
                "f_prom": D(sub[2]["factor_sueldo_formal"], 2), "cob_med": P(100 * np.mean([c["cobertura_mediana"] for c in cob]), 0),
                "cob_prom": P(100 * np.mean([c["cobertura_media"] for c in cob]), 0)},
        "stock_pico": D(hit["stock_pico_billones"]), "stock_hoy": D(hit["stock_ultimo_billones"]), "stock_pct_pico": P(hit["pct_del_pico"], 0),
        "mes_pico": mes(hit["mes_pico"]), "tasa_uva": P(hit["tasa_uva_ultima"], 2),
        "destino_compra": P(100 * (d26["compra_usada"] + d26["compra_nueva"]) / tot26, 0), "destino_mes": mes(d26["mes"]),
        "casi": C(K["segmentos"]["casi_elegibles_hogares"]), "k_seg": K["segmentos"]["info"]["k_optimo"],
        "silhouette": D(K["segmentos"]["info"]["silhouette"][str(K["segmentos"]["info"]["k_optimo"])], 2),
        "segmentos": [{"nombre": s["nombre"], "hogares": C(s["hogares"]), "edad": exacto(s["edad_mediana"]), "miembros": exacto(s["miembros_mediana"]),
                       "formal": P(s["pct_formal"], 0), "dos": P(s["pct_2_perceptores"], 0), "cobertura": P(100 * s["cobertura_mediana"], 0),
                       "ingreso": M(s["ingreso_mediano"])} for s in seg],
        "prestamo_medio": M(p["prestamo_medio_elegibles_ars"]), "fgs": M(K["fgs"]["monto_ars"]), "fgs_creditos": C(K["fgs"]["creditos_financiables_aprox"]),
        "fgs_veces": D(p["elegibles_hogares"] / K["fgs"]["creditos_financiables_aprox"], 0),
        "usd_m2": {"CABA": M(K["mercado"]["usd_m2"]["CABA"], "USD", exacto=True), "Gran Córdoba": M(K["mercado"]["usd_m2"]["Gran Córdoba"], "USD", exacto=True),
                   "GBA": M(K["mercado"]["usd_m2"]["Partidos del GBA"], "USD", exacto=True),
                   **{c: M(v, "USD", exacto=True) for c, v in K["mercado"]["usd_m2_corredor"].items()}},
        "tc": "$ " + D(K["mercado"]["tc_minorista"], 2), "uva": "$ " + D(K["mercado"]["uva"], 2),
        "ejemplos": [{"zona": e["zona"], "m2": e["m2"], "precio_usd": M(e["precio_usd"], "USD"), "cuota": M(e["cuota_ars"]),
                      "efectivo": M(e["efectivo_necesario_ars"]), "efectivo_usd": M(e["efectivo_necesario_usd"], "USD"),
                      "ingreso": M(e["ingreso_requerido"]), "anios": D(e["anios_ahorro_20pct_ingreso_mediano"], 0)}
                     for e in K["ejemplos_vivienda"] if e["m2"] == 60],
    }


def protagonista(K: dict) -> dict:
    """Hogar ilustrativo construido con datos: pareja con hijos, ingreso mediano de su grupo, 60 m² en GBA Oeste."""
    perfil = {(r["tipo_hogar"], r["jefatura"]): r for r in K["h3"]["perfil"]}
    ingreso = perfil[("Pareja con hijos", "Todas")]["ingreso_mediano"]
    usd_m2 = K["mercado"]["usd_m2_corredor"]["Oeste"]
    tc, uva, m2 = K["mercado"]["tc_minorista"], K["mercado"]["uva"], 60
    b = K["producto_base"]

    def calcular(plazo, ltv, factor_precio=1.0):
        precio = usd_m2 * m2 * tc * factor_precio
        prestamo = min(ltv * precio, b["tope_prestamo_uva"] * uva)
        cuota = prestamo * factor_cuota(b["tna"], plazo)
        efectivo = precio - prestamo + b["gastos_compra"] * precio
        return {"precio_usd": M(precio / tc, "USD"), "precio": M(precio), "cuota": M(cuota), "ratio": P(100 * cuota / ingreso, 0),
                "pasa_cuota": cuota / ingreso <= b["tope_cuota_ingreso"], "efectivo": M(efectivo), "efectivo_usd": M(efectivo / tc, "USD"),
                "meses": D(efectivo / ingreso, 0), "pasa_anticipo": efectivo / ingreso <= b["meses_ingreso_anticipo"],
                "anios_ahorro": D(efectivo / (0.20 * ingreso * 12), 0),
                "ingreso_req": M(max(cuota / b["tope_cuota_ingreso"], efectivo / b["meses_ingreso_anticipo"]))}

    return {"ingreso": M(ingreso), "m2": m2, "usd_m2": M(usd_m2, "USD", exacto=True), "base": calcular(20, 0.75),
            "propuesto": calcular(30, 0.80), "propuesto_barata": calcular(30, 0.80, 0.8)}


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
def exportar_pdf(html: Path, pdf: Path, titulo: str) -> None:
    if not EDGE.exists():
        print("  (Edge no encontrado: se omite el PDF)")
        return
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.resolve().as_uri()], check=True, timeout=240,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    limpiar_metadatos(pdf, titulo)


def limpiar_metadatos(pdf: Path, titulo: str) -> None:
    """Reescribe los metadatos del PDF: autor y título del proyecto, sin datos del software ni del equipo."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(pdf))
    writer = PdfWriter(clone_from=reader)
    writer.metadata = None
    writer.add_metadata({"/Title": titulo, "/Author": AUTOR, "/Subject": "¿Quién puede pagar hoy un crédito hipotecario UVA?",
                         "/Creator": AUTOR, "/Producer": AUTOR})
    if hasattr(writer, "xmp_metadata"):
        writer.xmp_metadata = None
    # Descarta objetos sueltos que el conversor deja en el archivo (por ejemplo, un bloque XMP sin referencia)
    writer.compress_identical_objects(remove_duplicates=False, remove_unreferenced=True)
    with open(pdf, "wb") as f:
        writer.write(f)


def markdown_a_pdf(md_path: Path, titulo: str) -> Path:
    """Convierte un .md del proyecto a HTML con los estilos compartidos y lo exporta a PDF."""
    import mistune
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)
    estilos = env.get_template("_estilos.html.j2").render()
    cuerpo = mistune.create_markdown(plugins=["table", "strikethrough"])(md_path.read_text(encoding="utf-8"))
    cuerpo = cuerpo.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    cuerpo = cuerpo.replace("<blockquote>", '<blockquote class="box callout">')
    html = (f'<!doctype html><html lang="es-AR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{titulo}</title>{estilos}'
            f'<style>blockquote{{margin:16px 0}} blockquote p{{margin:0}} h1{{font-size:26px}} td,th{{font-size:12.5px}}</style>'
            f'</head><body><main class="page">{cuerpo}</main></body></html>')
    md_path = md_path.resolve()
    html_path, pdf_path = md_path.with_suffix(".html"), md_path.with_suffix(".pdf")
    html_path.write_text(html, encoding="utf-8")
    exportar_pdf(html_path, pdf_path, titulo)
    return pdf_path


FIGURAS = ["02_eph_vs_censo", "03_embudo_elegibilidad", "03_precio_en_ingresos", "03_calor_m2_zona", "03_calor_m2_integrantes",
           "03_perfil_hogares", "04_logit_odds", "03_elegibles_por_zona_edad", "04_que_pasa_si", "04_que_lo_empeora",
           "04_grilla_plazo_ltv", "04_escenarios_producto", "05_independientes_embudo", "05_volatilidad_ingresos",
           "03_stress_uva_salarios", "03_sueldo_tres_lentes", "03_acceso_por_trabajos", "04_segmentos", "03_mercado_credito",
           "03_destino_credito", "03_m2_por_salario", "03_robustez"]


def main() -> None:
    K = json.loads((RESULTADOS / "kpis.json").read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH), read_only=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    f_pond, med = fig_ponderar(con)
    f_nr = fig_no_respuesta(con)
    n = numeros(con, K)
    con.close()

    figs = {"ponderar": data_uri(f_pond), "no_respuesta": data_uri(f_nr),
            "embudo_gcba": data_uri(FIGURES / "02_gcba_embudo_limpieza.svg")}
    for nombre in FIGURAS:
        if (FIGURES / f"{nombre}.png").exists():
            figs[nombre] = data_uri(FIGURES / f"{nombre}.png")
    med_fmt = {"ingenua_inq": M(med["ingenua_inq"]), "correcta_inq": M(med["correcta_inq"]),
               "caida_inq": P(100 * (1 - med["ingenua_inq"] / med["correcta_inq"]), 0)}

    contexto = dict(n=n, r=resultados(K), prot=protagonista(K), figs=figs, med=med_fmt, base=BASE, version=VERSION, autor=AUTOR,
                    fecha_corte=FECHA_CORTE.strftime("%d-%m-%Y"), fecha_doc=date.today().strftime("%d-%m-%Y"), P=P, M=M, C=C, D=D)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)
    for plantilla, nombre, titulo in [("documento_metodologico.html.j2", "documento_metodologico", "Documento metodológico · Crédito hipotecario UVA"),
                                      ("resumen_en_simple.html.j2", "resumen_en_simple", "Resumen en simple · Crédito hipotecario UVA")]:
        html_path, pdf_path = REPORTS / f"{nombre}.html", REPORTS / f"{nombre}.pdf"
        html_path.write_text(env.get_template(plantilla).render(**contexto), encoding="utf-8")
        exportar_pdf(html_path, pdf_path, titulo)
        print(f"  ✓ reports/{nombre}.html + PDF ({pdf_path.stat().st_size / 1e6:.1f} MB)")

    for md in ["02_insights", "03_recomendacion"]:
        (REPORTS / f"{md}.md").write_text(env.get_template(f"{md}.md.j2").render(**contexto), encoding="utf-8")
        print(f"  ✓ reports/{md}.md")
    (ROOT / "README.md").write_text(env.get_template("README.md.j2").render(**contexto), encoding="utf-8")
    print("  ✓ README.md")


if __name__ == "__main__":
    main()
