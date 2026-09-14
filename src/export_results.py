"""Persiste los resultados del análisis: CSV, kpis.json y datos del dashboard.

Uso:  .venv\\Scripts\\python.exe src\\export_results.py

Fuente única de verdad para dashboard, deck, documentos y portfolio: ningún número se escribe a mano.
"""
import json
import warnings

import duckdb
import numpy as np
import pandas as pd

import imputacion
import validacion_censo
from affordability import GBA, Producto, cargar_inquilinos, embudo, evaluar, factor_cuota, parametros_mercado
from analysis import (TIPOS_HOGAR, acceso_por_fuentes, casi_elegibles, cobertura_sipa, escenario_solo_titulares,
                      escenario_subdeclaracion, grilla_producto, grupo_geografico, h1_intervalos, h1_mapa_calor,
                      h2_barreras, h3_perfil_hogares, h4_por_grupo, logit_ponderado, modulo_independientes, que_pasa_si,
                      segmentar, volatilidad_ingresos, wquant)
from config import BASE, DB_PATH, FECHA_CORTE, PROCESSED, m2_por_hogar

warnings.filterwarnings("ignore")
OUT = PROCESSED / "resultados"
PRODUCTO_PROPUESTO = dict(plazo_anios=30, ltv=0.80)          # mejor combinación con tope de cuota 25% (grilla)
PROGRAMA_FGS_ARS = 2_000_000_000_000                          # $2 billones (10 licitaciones de $200.000 M)
ZONAS = ["CABA", "GBA Norte", "GBA Oeste", "GBA Sur", "Gran Córdoba"]


def nombrar_segmentos(perfil: pd.DataFrame) -> dict:
    nombres = {}
    for seg, r in perfil.iterrows():
        if r.pct_formal < 5 and r.cobertura_mediana >= 1:
            nombre = "Pueden pagar, pero sin recibo de sueldo"
        elif r.pct_formal < 5:
            nombre = "Sin ingreso demostrable y cerca de calificar"
        elif r.pct_2_perceptores >= 60:
            nombre = "Dos ingresos, a un paso de calificar"
        elif r.edad_mediana < 40:
            nombre = "Un ingreso, hogares jóvenes"
        else:
            nombre = "Un ingreso, hogares adultos"
        while nombre in nombres.values():
            nombre += " (b)"
        nombres[seg] = nombre
    return nombres


def ejemplos_vivienda(m: dict, p: Producto, ingreso_mediano: float) -> list[dict]:
    """Cuánto cuesta y cuánto hay que ganar para una vivienda típica, por zona y tamaño (para el relato)."""
    gba = m["gba_partidos"]
    precios = {"CABA": m["usd_m2"]["CABA"], "Gran Córdoba": m["usd_m2"]["Gran Córdoba"]}
    for c in ["Norte", "Oeste", "Sur"]:
        g = gba[gba.corredor == c]
        precios[f"GBA {c}"] = float(np.average(g.usd_m2, weights=g.peso_en_corredor))
    f = factor_cuota(p.tna, p.plazo_anios)
    filas = []
    for zona in ZONAS:
        for m2 in [45, 60, 75]:
            precio_usd = precios[zona] * m2
            precio_ars = precio_usd * m["tc"]
            prestamo = min(p.ltv * precio_ars, p.tope_prestamo_uva * m["uva"])
            cuota = prestamo * f
            efectivo = precio_ars - prestamo + p.gastos_compra * precio_ars
            filas.append({"zona": zona, "m2": m2, "usd_m2": precios[zona], "precio_usd": precio_usd, "precio_ars": precio_ars,
                          "prestamo_ars": prestamo, "cuota_ars": cuota, "efectivo_necesario_ars": efectivo,
                          "efectivo_necesario_usd": efectivo / m["tc"],
                          "ingreso_requerido_por_cuota": cuota / p.tope_cuota_ingreso,
                          "ingreso_requerido_por_anticipo": efectivo / p.meses_ingreso_anticipo,
                          "ingreso_requerido": max(cuota / p.tope_cuota_ingreso, efectivo / p.meses_ingreso_anticipo),
                          # Ilustrativo, en pesos constantes: años ahorrando el 20% del ingreso mediano de un hogar inquilino
                          "anios_ahorro_20pct_ingreso_mediano": efectivo / (0.20 * ingreso_mediano * 12)})
    return filas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    censo = validacion_censo.main(verbose=False)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    m = parametros_mercado(con)
    h = cargar_inquilinos(con)
    base = Producto()
    prop = base.con(**PRODUCTO_PROPUESTO)

    # ---- Resultado base
    ev = evaluar(h, m, base)
    ev["zona"] = grupo_geografico(ev)
    emb = embudo(ev)
    emb_merc = embudo(ev, "mercado")
    emb_zona = embudo(ev, "zona")
    ic = h1_intervalos(h, m, base)
    calor_zona, calor_integrantes = h1_mapa_calor(h, m, base)
    h2 = h2_barreras(ev, base)
    h3 = h3_perfil_hogares(h, m, base)
    h4_zona, t_zona = h4_por_grupo(h, m, "zona", base)
    h4_edad, t_edad = h4_por_grupo(h, m, "tramo_edad_jefe", base)
    mejoras, riesgos = que_pasa_si(h, m, base)
    grilla = grilla_producto(h, m, base)
    logit, logit_info = logit_ponderado(ev)
    casi = casi_elegibles(ev)
    casi_seg, perfil, seg_info = segmentar(casi)
    perfil.insert(0, "nombre", perfil.index.map(nombrar_segmentos(perfil)))
    fuentes = acceso_por_fuentes(h, m, base)
    titulares = escenario_solo_titulares(h, m, base)
    independientes = modulo_independientes(h, m, base)
    volatilidad = volatilidad_ingresos(con)
    cobertura = cobertura_sipa(con)
    subdeclaracion = escenario_subdeclaracion(h, m, cobertura, base)
    no_respuesta = imputacion.main(verbose=False)

    # ---- Producto propuesto
    ev_prop = evaluar(h, m, prop)
    ev_prop["zona"] = grupo_geografico(ev_prop)
    ev_prop_indep = evaluar(h, m, prop.con(acepta_independientes=True))
    prestamo_medio = np.average(ev_prop.prestamo_ars[ev_prop.elegible], weights=ev_prop.peso[ev_prop.elegible])

    # ---- Series (marts SQL)
    stress = con.execute("SELECT * FROM mart_stress_uva_salarios").df()
    stress_res = pd.read_csv(PROCESSED / "evidencia" / "04_marts" / "stress_resumen_ventanas.csv")
    hitos = pd.read_csv(PROCESSED / "evidencia" / "04_marts" / "mercado_credito_hitos.csv").iloc[0]
    mercado_credito = con.execute("SELECT * FROM mart_mercado_credito ORDER BY mes").df()
    m2_salario = con.execute("SELECT * FROM mart_m2_por_salario ORDER BY anio").df()
    tres_lentes = con.execute("SELECT * FROM mart_sueldo_tres_lentes ORDER BY mes").df()
    destino = con.execute("SELECT * FROM mart_destino_credito ORDER BY mes").df()
    universo = con.execute("""
        SELECT sum(pondera_ajust) AS hogares,
               sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino') AS inquilinos,
               sum(pondera_ajust) FILTER (WHERE tenencia = 'Propietario') AS propietarios,
               sum(pondera_ajust) FILTER (WHERE tenencia = 'Otra situación') AS otra_situacion,
               sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino' AND NOT ingreso_declarado) AS inquilinos_sin_ingreso_declarado,
               count(*) FILTER (WHERE tenencia = 'Inquilino') AS obs_inquilinos,
               count(DISTINCT hogar_id) FILTER (WHERE tenencia = 'Inquilino') AS hogares_encuestados_inquilinos,
               count(*) AS obs_total
        FROM hogares_eph
    """).df().iloc[0]
    universo_mercado = con.execute("""
        SELECT mercado, sum(pondera_ajust) AS hogares, sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino') AS inquilinos
        FROM hogares_eph GROUP BY 1 ORDER BY 1
    """).df()

    # Contexto de mercado (ex H6): correlación sin el período de bajo volumen, rezagos 0-12
    mc = mercado_credito.set_index("mes")
    h6 = []
    for lag in range(0, 13, 3):
        a = mc.assign(tasa_lag=mc.tasa_hip_uva.shift(lag)).dropna(subset=["crecimiento_real_12m_pct", "tasa_lag"])
        a = a[~a.periodo_bajo_volumen]
        h6.append({"rezago_meses": lag, "correlacion": a.crecimiento_real_12m_pct.corr(a.tasa_lag), "n": len(a)})
    h6 = pd.DataFrame(h6)

    # ---- CSV
    tablas = {
        "embudo_total": emb, "embudo_por_mercado": emb_merc, "embudo_por_zona": emb_zona, "h1_intervalos": ic,
        "h1_calor_zona": calor_zona, "h1_calor_integrantes": calor_integrantes, "h3_perfil_hogares": h3,
        "h4_zona": h4_zona, "h4_edad": h4_edad, "que_pasa_si": mejoras, "que_lo_empeora": riesgos,
        "grilla_producto": grilla, "logit_odds_ratios": logit, "segmentos_perfil": perfil.reset_index(),
        "contexto_correlaciones": h6, "embudo_producto_propuesto": embudo(ev_prop),
        "embudo_propuesto_por_zona": embudo(ev_prop, "zona"), "h7_acceso_por_trabajos": fuentes,
        "independientes_volatilidad": volatilidad, "subdeclaracion_cobertura_sipa": cobertura,
        "subdeclaracion_escenarios": subdeclaracion, "ejemplos_vivienda": pd.DataFrame(ejemplos_vivienda(m, base, wquant(h.ingreso, h.peso))),
    }
    for viejo in OUT.glob("*.csv"):
        viejo.unlink()
    for nombre, df in tablas.items():
        df.to_csv(OUT / f"{nombre}.csv", index=False)

    # ---- KPIs
    hog = lambda e: float(e.peso[e.elegible].sum())
    pct = lambda e: float(100 * e.peso[e.elegible].sum() / e.peso.sum())
    elegibles = hog(ev)
    ultimo_lentes = tres_lentes.iloc[-1]
    kpis = {
        "fecha_corte": FECHA_CORTE.isoformat(),
        "mercado": {"uva": m["uva"], "fecha_uva": str(m["fecha_uva"]), "tc_minorista": m["tc"], "fecha_tc": str(m["fecha_tc"]),
                    "usd_m2": m["usd_m2"],
                    "usd_m2_corredor": {c: float(np.average(g.usd_m2, weights=g.peso_en_corredor))
                                        for c, g in m["gba_partidos"].groupby("corredor")}},
        "producto_base": BASE,
        "m2_referencia": {"1-2 integrantes": m2_por_hogar(2), "3-4 integrantes": m2_por_hogar(4), "5 o más": m2_por_hogar(5)},
        "universo": {
            "hogares_3_mercados": float(universo.hogares), "inquilinos": float(universo.inquilinos),
            "propietarios": float(universo.propietarios), "otra_situacion": float(universo.otra_situacion),
            "pct_inquilinos": float(100 * universo.inquilinos / universo.hogares),
            "inquilinos_sin_ingreso_declarado": float(universo.inquilinos_sin_ingreso_declarado),
            "observaciones_inquilinos": int(universo.obs_inquilinos),
            "observaciones_inquilinos_con_ingreso": int(len(h)),
            "hogares_encuestados_inquilinos_con_ingreso": int(h.hogar_id.nunique()),
            "observaciones_total": int(universo.obs_total),
            "por_mercado": universo_mercado.to_dict(orient="records"),
            "censo": censo,
        },
        "base": {
            "elegibles_hogares": elegibles, "elegibles_pct": float(ic.loc[1, "pct"]),
            "elegibles_ic95": [float(ic.loc[1, "ic95_inf"]), float(ic.loc[1, "ic95_sup"])],
            "elegibles_rango_censo": [elegibles * censo["factor_ajuste_min"], elegibles * censo["factor_ajuste_max"]],
            "pasan_cuota_pct": float(ic.loc[0, "pct"]), "pasan_cuota_ic95": [float(ic.loc[0, "ic95_inf"]), float(ic.loc[0, "ic95_sup"])],
            "pasan_cuota_hogares": float(ev.peso[ev.pasa_cuota].sum()),
            "embudo": emb.to_dict(orient="records"),
            "queda_afuera_en_pct": (ev.groupby("queda_afuera_en").peso.sum() / ev.peso.sum() * 100).to_dict(),
            "ingreso_mediano_inquilinos": wquant(h.ingreso, h.peso),
            "ingreso_mediano_elegibles": wquant(ev.ingreso[ev.elegible], ev.peso[ev.elegible]),
            "prestamo_medio_elegibles_ars": float(np.average(ev.prestamo_ars[ev.elegible], weights=ev.peso[ev.elegible])),
        },
        "h1": {"calor_zona": calor_zona.to_dict(orient="records"), "calor_integrantes": calor_integrantes.to_dict(orient="records")},
        "h2": h2,
        "h3": {"perfil": h3.to_dict(orient="records"), "tipos": TIPOS_HOGAR},
        "h4": {"test_zona": t_zona, "test_edad": t_edad,
               "por_zona": h4_zona.to_dict(orient="records"), "por_edad": h4_edad.to_dict(orient="records")},
        "h5": {"stress_resumen": stress_res.to_dict(orient="records"),
               "sueldo_ultimo": {"mes": str(ultimo_lentes.mes)[:7], "bruto": float(ultimo_lentes.sueldo_bruto),
                                 "usd_bna": float(ultimo_lentes.sueldo_usd_bna), "real_ago26": float(ultimo_lentes.sueldo_real_pesos_ago26)},
               "sueldo_hitos": pd.read_csv(PROCESSED / "evidencia" / "04_marts" / "sueldo_tres_lentes_hitos.csv").to_dict(orient="records"),
               "independientes": independientes, "volatilidad": volatilidad.to_dict(orient="records")},
        "contexto_mercado": {"hitos": hitos.to_dict(), "correlaciones": h6.to_dict(orient="records"),
                             "destino_ultimo": pd.read_csv(PROCESSED / "evidencia" / "04_marts" / "destino_credito_ultimo.csv").to_dict(orient="records")},
        "h7": {"por_trabajos": fuentes.to_dict(orient="records"), "solo_titulares": titulares},
        "que_pasa_si": mejoras.to_dict(orient="records"), "que_lo_empeora": riesgos.to_dict(orient="records"),
        "logit": {"info": logit_info, "odds_ratios": logit.to_dict(orient="records")},
        "segmentos": {"info": seg_info, "casi_elegibles_hogares": float(casi.peso.sum()),
                      "perfil": perfil.reset_index().to_dict(orient="records")},
        "robustez": {
            "subdeclaracion": {"cobertura": cobertura.to_dict(orient="records"), "escenarios": subdeclaracion.to_dict(orient="records")},
            "no_respuesta": no_respuesta,
        },
        "producto_propuesto": {
            "parametros": PRODUCTO_PROPUESTO,
            "elegibles_hogares": hog(ev_prop), "elegibles_pct": pct(ev_prop),
            "delta_vs_base_hogares": hog(ev_prop) - elegibles, "delta_vs_base_pct": 100 * (hog(ev_prop) / elegibles - 1),
            "por_zona": embudo(ev_prop, "zona").query("etapa == 'Cumplen la edad'").to_dict(orient="records"),
            "con_independientes_hogares": hog(ev_prop_indep), "con_independientes_pct": pct(ev_prop_indep),
            "con_independientes_delta_vs_base_pct": 100 * (hog(ev_prop_indep) / elegibles - 1),
            "factor_cuota_base": factor_cuota(base.tna, base.plazo_anios), "factor_cuota_propuesto": factor_cuota(prop.tna, prop.plazo_anios),
            "prestamo_medio_elegibles_ars": float(prestamo_medio),
        },
        "fgs": {"monto_ars": PROGRAMA_FGS_ARS, "creditos_financiables_aprox": PROGRAMA_FGS_ARS / prestamo_medio},
        "ejemplos_vivienda": ejemplos_vivienda(m, base, wquant(h.ingreso, h.peso)),
    }
    (OUT / "kpis.json").write_text(json.dumps(kpis, indent=2, ensure_ascii=False, default=float), encoding="utf-8")

    # ---- Datos del dashboard: subconjunto anonimizado de microdatos públicos (sin CODUSU ni identificadores)
    mercados = ["CABA", GBA, "Gran Córdoba"]
    filas = [[mercados.index(r.mercado), int(r.miembros), int(bool(r.hogar_formal)), int(bool(r.jefe_o_conyuge_indep_registrado)),
              int(r.jefe_edad), int(round(r.ingreso, -3)), round(float(r.peso), 1), TIPOS_HOGAR.index(r.tipo_hogar)]
             for r in h.sample(frac=1, random_state=7).itertuples()]
    gba = m["gba_partidos"]
    dash = {
        "fecha_corte": FECHA_CORTE.isoformat(),
        "mercado": {"uva": m["uva"], "tc": m["tc"], "nombres": mercados,
                    "usd_m2": {"CABA": m["usd_m2"]["CABA"], "Gran Córdoba": m["usd_m2"]["Gran Córdoba"]},
                    "gba_partidos": [{"partido": r.partido, "corredor": r.corredor, "usd_m2": round(float(r.usd_m2), 1),
                                      "peso_gba": round(float(r.peso_en_gba), 6), "peso_corredor": round(float(r.peso_en_corredor), 6),
                                      "imputado": bool(r.precio_imputado_por_corredor)} for r in gba.itertuples()]},
        "base": {k: BASE[k] for k in ["tna", "plazo_anios", "ltv", "tope_cuota_ingreso", "gastos_compra", "tope_prestamo_uva",
                                      "meses_ingreso_anticipo", "edad_max_fin_credito"]},
        "propuesto": PRODUCTO_PROPUESTO,
        "hogares_campos": ["mercado", "miembros", "formal", "independiente", "edad_jefe", "ingreso_ago26", "peso", "tipo_hogar"],
        "tipos_hogar": TIPOS_HOGAR,
        "hogares": filas,
        "kpis": {"inquilinos": kpis["universo"]["inquilinos"], "hogares": kpis["universo"]["hogares_3_mercados"],
                 "elegibles_base": elegibles, "elegibles_pct": kpis["base"]["elegibles_pct"], "ic95": kpis["base"]["elegibles_ic95"],
                 "rango_censo": kpis["base"]["elegibles_rango_censo"], "pasan_cuota_pct": kpis["base"]["pasan_cuota_pct"],
                 "propuesto": hog(ev_prop), "propuesto_indep": hog(ev_prop_indep),
                 "casi_elegibles": kpis["segmentos"]["casi_elegibles_hogares"],
                 "imputacion_pct": no_respuesta["pct_elegible_imputacion"]["estimacion"],
                 "subdeclaracion_pct": [float(x) for x in subdeclaracion.pct_elegible]},
        "embudo": emb[["etapa", "hogares"]].round(0).to_dict(orient="records"),
        "embudo_zona": emb_zona[["zona", "etapa", "hogares", "pct_del_total"]].round(2).to_dict(orient="records"),
        "calor_zona": calor_zona.round(2).to_dict(orient="records"),
        "calor_integrantes": calor_integrantes.round(2).to_dict(orient="records"),
        "h3": h3[h3.agrupacion != "tipo_hogar × jefatura"][["tipo_hogar", "jefatura", "hogares", "pct_de_inquilinos", "ingreso_mediano",
                                                           "pct_ingreso_demostrable", "pct_elegible", "ic95_inf", "ic95_sup",
                                                           "muestra_hogares"]].round(1).to_dict(orient="records"),
        "h7": fuentes[fuentes.variable == "detalle_trabajo"][["grupo", "hogares", "pct_de_inquilinos", "pct_elegible", "ic95_inf",
                                                              "ic95_sup", "muestra_hogares"]].round(1).to_dict(orient="records"),
        "que_pasa_si": mejoras[["pregunta", "hogares", "diferencia", "por_que"]].round(0).to_dict(orient="records"),
        "que_lo_empeora": riesgos[["pregunta", "hogares", "diferencia"]].round(0).to_dict(orient="records"),
        "mercado_credito": [{"mes": str(r.mes)[:7], "stock": None if pd.isna(r.stock_real_billones_ago26) else round(r.stock_real_billones_ago26, 3),
                             "tasa": None if pd.isna(r.tasa_hip_uva) else round(r.tasa_hip_uva, 2),
                             "bajo_volumen": bool(r.periodo_bajo_volumen)} for r in mercado_credito.itertuples()],
        "destino": [{"mes": str(r.mes)[:7], "usada": round(r.compra_usada_billones_ago26, 3), "nueva": round(r.compra_nueva_billones_ago26, 3),
                     "construccion": round(r.construccion_billones_ago26, 3), "refaccion": round(r.refaccion_billones_ago26, 3),
                     "otros": round(r.otros_billones_ago26, 3)} for r in destino.itertuples()],
        "stress": {ini: stress[stress.inicio == pd.Timestamp(ini)].sort_values("meses_transcurridos")[["meses_transcurridos", "cuota_ingreso"]]
                   .round(4).values.tolist() for ini in ["2018-05-01", "2023-09-01"]},
        "stress_24m": [{"inicio": str(r.inicio)[:7], "cuota_ingreso": round(r.cuota_ingreso, 4)}
                       for r in stress[stress.meses_transcurridos == 24].sort_values("inicio").itertuples()],
        "sueldo_tres_lentes": [{"mes": str(r.mes)[:7], "indice_sueldo": round(r.indice_sueldo, 1), "indice_ipc": round(r.indice_ipc, 1),
                                "indice_uva": round(r.indice_uva, 1), "usd_bna": round(r.sueldo_usd_bna), "real_ago26": round(r.sueldo_real_pesos_ago26, -3)}
                               for r in tres_lentes.itertuples()],
        "m2_por_salario": [{"anio": int(r.anio), "m2": round(r.m2_por_salario, 3), "fuente": r.fuente_precio} for r in m2_salario.itertuples()],
        "segmentos": [{"nombre": r.nombre, "hogares": round(r.hogares), "ingreso_mediano": round(r.ingreso_mediano, -3),
                       "cobertura": round(r.cobertura_mediana, 2), "edad": int(r.edad_mediana), "miembros": int(r.miembros_mediana),
                       "pct_formal": round(r.pct_formal, 1), "pct_2_perceptores": round(r.pct_2_perceptores, 1)} for r in perfil.itertuples()],
        "zonas": h4_zona[["zona", "pct_elegible", "ic95_inf", "ic95_sup", "hogares", "hogares_elegibles"]].round(2).to_dict(orient="records"),
        "edades": h4_edad[["tramo_edad_jefe", "pct_elegible", "ic95_inf", "ic95_sup", "hogares_elegibles"]].round(2).to_dict(orient="records"),
        "independientes": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in independientes.items()},
        "volatilidad": volatilidad.round(1).to_dict(orient="records"),
        "robustez": {"base": [kpis["base"]["elegibles_pct"], *kpis["base"]["elegibles_ic95"]],
                     "imputacion": [no_respuesta["pct_elegible_imputacion"][c] for c in ["estimacion", "ic95_inf", "ic95_sup"]],
                     "sipa_mediana": float(subdeclaracion.pct_elegible.iloc[1]), "sipa_promedio": float(subdeclaracion.pct_elegible.iloc[2])},
        "fgs": {"monto": PROGRAMA_FGS_ARS, "creditos": kpis["fgs"]["creditos_financiables_aprox"], "prestamo_medio": float(prestamo_medio)},
        "ejemplos": [e for e in kpis["ejemplos_vivienda"]],
        "stress_resumen": stress_res.to_dict(orient="records"),
        "hitos_credito": hitos.to_dict(),
    }
    (OUT / "dashboard_data.json").write_text(json.dumps(dash, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"  ✓ {len(tablas)} CSV + kpis.json + dashboard_data.json en {OUT.name}/")
    print(f"  Inquilinos {universo.inquilinos:,.0f} · elegibles base {elegibles:,.0f} ({kpis['base']['elegibles_pct']:.1f}%, "
          f"IC {ic.loc[1, 'ic95_inf']:.1f}-{ic.loc[1, 'ic95_sup']:.1f}) · rango Censo {kpis['base']['elegibles_rango_censo'][0]:,.0f}-"
          f"{kpis['base']['elegibles_rango_censo'][1]:,.0f}")
    print(f"  Propuesto {hog(ev_prop):,.0f} (+{kpis['producto_propuesto']['delta_vs_base_pct']:.0f}%) · con independientes "
          f"{hog(ev_prop_indep):,.0f} (+{kpis['producto_propuesto']['con_independientes_delta_vs_base_pct']:.0f}%)")
    print(f"  Imputación {no_respuesta['pct_elegible_imputacion']['estimacion']:.1f}% · subdeclaración "
          f"{subdeclaracion.pct_elegible.min():.1f}-{subdeclaracion.pct_elegible.max():.1f}% · segmentos k={seg_info['k_optimo']}")
    print(f"  Préstamo medio (propuesto) ${prestamo_medio:,.0f} · FGS financia ~{kpis['fgs']['creditos_financiables_aprox']:,.0f} créditos")


if __name__ == "__main__":
    main()
