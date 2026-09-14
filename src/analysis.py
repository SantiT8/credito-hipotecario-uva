"""Análisis: hipótesis, sensibilidad, modelo, segmentación y escenarios de robustez.

Los notebooks narran y grafican; export_results.py persiste. Ambos llaman a estas funciones,
así las cifras del informe, del dashboard y del deck son siempre las mismas.
"""
import itertools

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.metrics import roc_auc_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from affordability import GBA, Producto, bootstrap_evaluado, evaluar, factor_cuota
from config import APORTES_TRABAJADOR

SEMILLA = 2026


def wquant(x, w, q: float = 0.5) -> float:
    x, w = np.asarray(x, float), np.asarray(w, float)
    o = np.argsort(x)
    xs, ws = x[o], w[o]
    return float(xs[min(np.searchsorted(np.cumsum(ws) / ws.sum(), q), len(xs) - 1)])


def grupo_geografico(ev: pd.DataFrame) -> pd.Series:
    """CABA / GBA Norte / GBA Oeste / GBA Sur / Gran Córdoba."""
    return np.where(ev.mercado == GBA, "GBA " + ev.corredor.astype(str), ev.mercado)


# ---------------------------------------------------------------------------
# H1 · cuántos pagan la cuota, y mapa de calor por superficie
# ---------------------------------------------------------------------------
def h1_intervalos(h: pd.DataFrame, m: dict, p: Producto = Producto(), B: int = 1000) -> pd.DataFrame:
    ev = evaluar(h, m, p)
    filas = []
    for col, nombre in [("pasa_cuota", "Pagan la cuota"), ("elegible", "Elegibles (embudo completo)")]:
        punto, lo, hi = bootstrap_evaluado(ev, col, B=B, semilla=SEMILLA)
        filas.append({"indicador": nombre, "pct": punto, "ic95_inf": lo, "ic95_sup": hi})
    return pd.DataFrame(filas)


M2_RANGO = list(range(30, 95, 5))


def h1_mapa_calor(h: pd.DataFrame, m: dict, p: Producto = Producto()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """% de inquilinos elegibles si todos buscaran X m²: por zona y por cantidad de integrantes."""
    zona, miembros = [], []
    for m2 in M2_RANGO:
        ev = evaluar(h, m, p.con(m2_fijo=m2))
        ev["zona"] = grupo_geografico(ev)
        ev["integrantes"] = pd.cut(ev.miembros, [0, 1, 2, 3, 4, 99], labels=["1", "2", "3", "4", "5 o más"]).astype(str)
        for g, d in ev.groupby("zona"):
            zona.append({"m2": m2, "zona": g, "pct_elegible": 100 * d.peso[d.elegible].sum() / d.peso.sum()})
        zona.append({"m2": m2, "zona": "Total", "pct_elegible": 100 * ev.peso[ev.elegible].sum() / ev.peso.sum()})
        for g, d in ev.groupby("integrantes"):
            miembros.append({"m2": m2, "integrantes": g, "pct_elegible": 100 * d.peso[d.elegible].sum() / d.peso.sum()})
    return pd.DataFrame(zona), pd.DataFrame(miembros)


# ---------------------------------------------------------------------------
# H2 · anticipo vs cuota
# ---------------------------------------------------------------------------
def h2_barreras(ev: pd.DataFrame, p: Producto = Producto()) -> dict:
    """Cuota y anticipo dependen del mismo cociente precio/ingreso: ¿cuál es más exigente?"""
    w = ev.peso
    tot = w.sum()
    f = factor_cuota(p.tna, p.plazo_anios)
    precio_max_cuota = p.tope_cuota_ingreso / (p.ltv * f)
    precio_max_anticipo = p.meses_ingreso_anticipo / (1 - p.ltv + p.gastos_compra)
    ltv_equilibrio = p.tope_cuota_ingreso * (1 + p.gastos_compra) / (p.tope_cuota_ingreso + p.meses_ingreso_anticipo * f)
    precio_en_ingresos = ev.precio_ars / ev.ingreso.where(ev.ingreso > 0)
    return {
        "pct_fallan_ambos": 100 * w[~ev.pasa_cuota & ~ev.pasa_anticipo].sum() / tot,
        "pct_solo_falla_anticipo": 100 * w[ev.pasa_cuota & ~ev.pasa_anticipo].sum() / tot,
        "pct_solo_falla_cuota": 100 * w[~ev.pasa_cuota & ev.pasa_anticipo].sum() / tot,
        "pct_pasan_ambos": 100 * w[ev.pasa_cuota & ev.pasa_anticipo].sum() / tot,
        "precio_max_ingresos_por_cuota": precio_max_cuota,
        "precio_max_ingresos_por_anticipo": precio_max_anticipo,
        "barrera_activa": "anticipo" if precio_max_anticipo < precio_max_cuota else "cuota",
        "ltv_equilibrio": ltv_equilibrio,
        "precio_max_ingresos_en_equilibrio": p.tope_cuota_ingreso / (ltv_equilibrio * f),
        "mediana_precio_en_ingresos": wquant(precio_en_ingresos.fillna(np.inf).clip(upper=1e6), w),
    }


# ---------------------------------------------------------------------------
# H3 · composición del hogar (descriptivo, neutral)
# ---------------------------------------------------------------------------
MUESTRA_MINIMA = 50  # hogares encuestados: por debajo, el dato se muestra pero se marca como poco preciso
TIPOS_HOGAR = ["Unipersonal", "Pareja sin hijos", "Pareja con hijos", "Monoparental", "Extendido o compuesto"]


def h3_perfil_hogares(h: pd.DataFrame, m: dict, p: Producto = Producto(), B: int = 500) -> pd.DataFrame:
    """Distribución y resultados por tipo de hogar × sexo de quien encabeza el hogar. Descriptivo, sin causalidad."""
    ev = evaluar(h, m, p)
    ev["jefatura"] = np.where(ev.jefe_sexo == 2, "Mujer", "Varón")
    total = ev.peso.sum()
    filas = []
    grupos = [("tipo_hogar", None), ("jefatura", None), ("tipo_hogar", "jefatura")]
    for g1, g2 in grupos:
        claves = [g1] if g2 is None else [g1, g2]
        for k, d in ev.groupby(claves):
            k = k if isinstance(k, tuple) else (k,)
            punto, lo, hi = bootstrap_evaluado(d, "elegible", B=B, semilla=SEMILLA)
            filas.append({
                "agrupacion": " × ".join(claves),
                "tipo_hogar": k[0] if g1 == "tipo_hogar" else "Todos",
                "jefatura": k[-1] if "jefatura" in claves else "Todas",
                "hogares": d.peso.sum(), "pct_de_inquilinos": 100 * d.peso.sum() / total,
                "muestra_hogares": d.hogar_id.nunique(),
                "ingreso_mediano": wquant(d.ingreso, d.peso), "ingreso_por_persona_mediano": wquant(d.ingreso_por_persona_ago26, d.peso),
                "perceptores_promedio": np.average(d.perceptores_ingreso, weights=d.peso),
                "pct_ingreso_demostrable": 100 * d.peso[d.hogar_formal.astype(bool)].sum() / d.peso.sum(),
                "pct_pasan_cuota_y_anticipo": 100 * d.peso[d.pasa_cuota & d.pasa_anticipo].sum() / d.peso.sum(),
                "pct_elegible": punto, "ic95_inf": lo, "ic95_sup": hi,
                "muestra_chica": d.hogar_id.nunique() < MUESTRA_MINIMA,
            })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# H4 · diferencias por zona y edad
# ---------------------------------------------------------------------------
def _kish_deff(w: np.ndarray) -> float:
    return len(w) * (w ** 2).sum() / w.sum() ** 2


def h4_por_grupo(h: pd.DataFrame, m: dict, grupo: str, p: Producto = Producto(), B: int = 1000) -> tuple[pd.DataFrame, dict]:
    """grupo: 'zona' (CABA, GBA por corredor, Córdoba), 'mercado' o 'tramo_edad_jefe'."""
    ev = evaluar(h, m, p)
    if grupo == "zona":
        ev["zona"] = grupo_geografico(ev)
    filas = []
    for g, sub in ev.groupby(grupo):
        punto, lo, hi = bootstrap_evaluado(sub, "elegible", B=B, semilla=SEMILLA)
        filas.append({grupo: g, "muestra_hogares": sub.hogar_id.nunique(), "hogares": sub.peso.sum(),
                      "hogares_elegibles": sub.peso[sub.elegible].sum(), "pct_elegible": punto, "ic95_inf": lo, "ic95_sup": hi})
    tabla = pd.DataFrame(filas).sort_values("pct_elegible", ascending=False)

    # Chi-cuadrado sobre conteos ponderados reescalados a n hogares, ajustado por efecto de diseño de Kish.
    # Por zona, el test se hace entre mercados: los corredores del GBA son los MISMOS hogares evaluados con
    # distintos precios (escenarios), no muestras independientes.
    g_test = "mercado" if grupo == "zona" else grupo
    ev = ev.assign(_wf=ev.peso * ev.elegible)
    por_hogar = ev.groupby(["hogar_id", g_test]).agg(w=("peso", "sum"), wf=("_wf", "sum")).reset_index()
    por_hogar["e"] = por_hogar.wf / por_hogar.w
    n = len(por_hogar)
    wn = por_hogar.w * n / por_hogar.w.sum()
    cont = pd.DataFrame({"si": (wn * por_hogar.e).groupby(por_hogar[g_test]).sum(),
                         "no": (wn * (1 - por_hogar.e)).groupby(por_hogar[g_test]).sum()})
    chi2, _, gl, _ = stats.chi2_contingency(cont, correction=False)
    deff = _kish_deff(por_hogar.w.to_numpy())
    chi2_aj = chi2 / deff
    test = {"test_entre": g_test, "chi2": chi2, "deff_kish": deff, "chi2_ajustado": chi2_aj, "gl": gl, "p_valor": stats.chi2.sf(chi2_aj, gl),
            "diferencia_max_pp": tabla.pct_elegible.max() - tabla.pct_elegible.min(), "muestra_hogares": int(n)}
    return tabla, test


# ---------------------------------------------------------------------------
# ¿Qué pasa si…? (medidas del banco) y ¿Qué lo empeora? (riesgos)
# ---------------------------------------------------------------------------
QUE_PASA_SI = [
    ("¿Y si el banco presta a 30 años en vez de 20?", dict(plazo_anios=30),
     "Baja la cuota, pero el anticipo no cambia y deja afuera a quienes tienen más de 55 años"),
    ("¿Y si financia el 80% en vez del 75%?", dict(ltv=0.80),
     "Baja el efectivo necesario, pero sube la cuota"),
    ("¿Y si hace las dos cosas: 30 años y 80%?", dict(plazo_anios=30, ltv=0.80),
     "El plazo largo compensa la cuota más alta y el anticipo baja"),
    ("¿Y si la tasa baja de 7,5% a 5,5%?", dict(tna=0.055),
     "Solo abarata la cuota; lo que frena es el anticipo"),
    ("¿Y si acepta cuotas de hasta 30% del ingreso?", dict(tope_cuota_ingreso=0.30),
     "Mismo motivo: la cuota no es el freno principal, y sube el riesgo"),
    ("¿Y si un plan de ahorro permite juntar 24 meses de ingreso?", dict(meses_ingreso_anticipo=24),
     "Ataca directamente el anticipo, que es el freno principal"),
    ("¿Y si acepta monotributistas y autónomos con aportes?", dict(acepta_independientes=True),
     "Suma hogares que pueden pagar pero no tienen recibo de sueldo"),
    ("¿Y si se compra una vivienda 20% más barata (usada o más chica)?", dict(factor_precio=0.8),
     "Reduce cuota y anticipo a la vez"),
]
QUE_LO_EMPEORA = [
    ("Si los precios suben 20%", dict(factor_precio=1.2)),
    ("Si la tasa sube a 9,5%", dict(tna=0.095)),
    ("Si el banco exige cuota de hasta 20% del ingreso", dict(tope_cuota_ingreso=0.20)),
    ("Si el anticipo hay que juntarlo en 6 meses de ingreso", dict(meses_ingreso_anticipo=6)),
    ("Si la edad máxima al terminar de pagar baja a 75", dict(edad_max_fin_credito=75)),
]


def que_pasa_si(h: pd.DataFrame, m: dict, base: Producto = Producto()) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev0 = evaluar(h, m, base)
    hog0 = ev0.peso[ev0.elegible].sum()

    def _fila(pregunta, cambios, por_que=""):
        ev = evaluar(h, m, base.con(**cambios))
        hog = ev.peso[ev.elegible].sum()
        return {"pregunta": pregunta, "hogares_base": hog0, "hogares": hog, "diferencia": hog - hog0,
                "diferencia_pct": 100 * (hog / hog0 - 1), "por_que": por_que}

    mejoras = pd.DataFrame([_fila(q, c, pq) for q, c, pq in QUE_PASA_SI])
    riesgos = pd.DataFrame([_fila(q, c) for q, c in QUE_LO_EMPEORA])
    return mejoras, riesgos


def grilla_producto(h: pd.DataFrame, m: dict, base: Producto = Producto()) -> pd.DataFrame:
    filas = []
    for plazo, ltv, tope in itertools.product([15, 20, 25, 30], [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90], [0.25, 0.30]):
        ev = evaluar(h, m, base.con(plazo_anios=plazo, ltv=ltv, tope_cuota_ingreso=tope))
        filas.append({"plazo_anios": plazo, "ltv": ltv, "tope_cuota_ingreso": tope,
                      "hogares": ev.peso[ev.elegible].sum(), "pct_elegible": 100 * ev.peso[ev.elegible].sum() / ev.peso.sum()})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Robustez 1 · subdeclaración de ingresos (EPH vs SIPA)
# ---------------------------------------------------------------------------
MES_REFERENCIA = {(2025, 2): "2025-05-01", (2025, 3): "2025-08-01", (2025, 4): "2025-11-01", (2026, 1): "2026-02-01"}


def cobertura_sipa(con) -> pd.DataFrame:
    """Cuánto del sueldo formal registrado (SIPA) capta la EPH, por trimestre (asalariados privados con aportes)."""
    eph = con.execute("""
        WITH a AS (
            SELECT CAST(ANO4 AS INT) AS anio, CAST(TRIMESTRE AS INT) AS trimestre,
                   TRY_CAST(P21 AS DOUBLE) AS p21, CAST(PONDIIO AS DOUBLE) AS w
            FROM stg_eph_individual
            WHERE ESTADO = '1' AND CAT_OCUP = '3' AND PP07H = '1' AND PP04A = '2'
              AND CAST(PONDIIO AS DOUBLE) > 0 AND TRY_CAST(P21 AS DOUBLE) > 0
        ), o AS (
            SELECT *, sum(w) OVER (PARTITION BY anio, trimestre ORDER BY p21) AS acum,
                   sum(w) OVER (PARTITION BY anio, trimestre) AS tot FROM a
        )
        SELECT anio, trimestre, sum(p21 * w) / sum(w) AS eph_media, min(p21) FILTER (WHERE acum >= tot / 2) AS eph_mediana
        FROM o GROUP BY ALL ORDER BY ALL
    """).df()
    sipa = con.execute("SELECT mes, sipa_remuneracion_promedio, sipa_remuneracion_mediana FROM series_mensuales").df()
    sipa["mes"] = pd.to_datetime(sipa.mes)
    filas = []
    for r in eph.itertuples():
        mes = pd.Timestamp(MES_REFERENCIA[(r.anio, r.trimestre)])
        s = sipa[sipa.mes == mes].iloc[0]
        neto_media, neto_mediana = s.sipa_remuneracion_promedio * (1 - APORTES_TRABAJADOR), s.sipa_remuneracion_mediana * (1 - APORTES_TRABAJADOR)
        filas.append({"trimestre": f"{r.trimestre}T-{r.anio}", "eph_media": r.eph_media, "sipa_media_neta": neto_media,
                      "cobertura_media": r.eph_media / neto_media, "eph_mediana": r.eph_mediana,
                      "sipa_mediana_neta": neto_mediana, "cobertura_mediana": r.eph_mediana / neto_mediana})
    return pd.DataFrame(filas)


def escenario_subdeclaracion(h: pd.DataFrame, m: dict, cobertura: pd.DataFrame, p: Producto = Producto()) -> pd.DataFrame:
    """Corrige solo los sueldos formales (que tienen referencia administrativa) por la cobertura medida contra el SIPA."""
    factor_mediana = 1 / cobertura.cobertura_mediana.mean()
    factor_media = 1 / cobertura.cobertura_media.mean()
    filas = []
    for nombre, f in [("Sin corregir (base)", 1.0), ("Corregido por la mediana", factor_mediana), ("Corregido por el promedio", factor_media)]:
        hh = h.assign(ingreso=h.ingreso + (f - 1) * h.ingreso_asalariado_formal_ago26)
        ev = evaluar(hh, m, p)
        filas.append({"escenario": nombre, "factor_sueldo_formal": f, "hogares_elegibles": ev.peso[ev.elegible].sum(),
                      "pct_elegible": 100 * ev.peso[ev.elegible].sum() / ev.peso.sum()})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Módulo independientes (no altera la base)
# ---------------------------------------------------------------------------
def modulo_independientes(h: pd.DataFrame, m: dict, p: Producto = Producto()) -> dict:
    ev_base = evaluar(h, m, p)
    ev_ind = evaluar(h, m, p.con(acepta_independientes=True))
    nuevos = ev_ind[ev_ind.elegible & ~ev_base.elegible.to_numpy()]
    solo_indep = ev_base[ev_base.jefe_o_conyuge_indep_registrado.astype(bool) & ~ev_base.hogar_formal.astype(bool)]
    social = ev_base[ev_base.jefe_o_conyuge_monotributo_social.astype(bool)]
    return {
        "inquilinos_con_independiente_registrado": ev_base.peso[ev_base.jefe_o_conyuge_indep_registrado.astype(bool)].sum(),
        "inquilinos_solo_independiente_sin_asalariado_formal": solo_indep.peso.sum(),
        "de_ellos_pasan_cuota_y_anticipo": solo_indep.peso[solo_indep.pasa_cuota & solo_indep.pasa_anticipo].sum(),
        "elegibles_base": ev_base.peso[ev_base.elegible].sum(),
        "elegibles_aceptando_independientes": ev_ind.peso[ev_ind.elegible].sum(),
        "hogares_que_se_suman": nuevos.peso.sum(),
        "ingreso_mediano_de_los_que_se_suman": wquant(nuevos.ingreso, nuevos.peso) if len(nuevos) else np.nan,
        "inquilinos_con_monotributo_social": social.peso.sum(),
        "monotributo_social_pasan_cuota_y_anticipo": social.peso[social.pasa_cuota & social.pasa_anticipo].sum(),
    }


# ---------------------------------------------------------------------------
# H3 complemento · logit ponderado con errores por conglomerado (hogar)
# ---------------------------------------------------------------------------
NIVEL_ED = {1: "Hasta secundario incompleto", 2: "Hasta secundario incompleto", 3: "Hasta secundario incompleto",
            7: "Hasta secundario incompleto", 4: "Secundario completo", 5: "Superior incompleto", 6: "Superior completo"}


def preparar_modelo(ev: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    # Una fila por observación hogar-trimestre. Resultado: proporción (ponderada) de la grilla de precios en la que el
    # hogar pasa cuota y anticipo. Fuera del GBA vale 0 o 1; en el GBA puede ser intermedia (logit fraccional).
    ev = ev.assign(paso=(ev.pasa_cuota & ev.pasa_anticipo).astype(float) * ev.peso)
    obs = ev.groupby(["hogar_id", "periodo"]).agg(peso=("peso", "sum"), paso=("paso", "sum")).reset_index()
    attrs = ev.drop_duplicates(["hogar_id", "periodo"]).set_index(["hogar_id", "periodo"])
    d = obs.join(attrs.drop(columns=["peso", "paso"], errors="ignore"), on=["hogar_id", "periodo"])
    d["y"] = (d.paso / d.peso).clip(0, 1)
    d["educacion"] = d.jefe_nivel_ed.map(NIVEL_ED).fillna("Hasta secundario incompleto")
    d["dos_o_mas_perceptores"] = (d.perceptores_ingreso >= 2).astype(float)
    d["jefatura_mujer"] = (d.jefe_sexo == 2).astype(float)
    d["situacion"] = d.jefe_situacion_laboral.replace({"Patrón": "Cuenta propia / patrón", "Cuenta propia": "Cuenta propia / patrón",
                                                        "Otro ocupado": "No ocupado"})
    d["edad"] = d.tramo_edad_jefe.replace({"18-29": "Hasta 29"})
    X = pd.get_dummies(d[["mercado", "edad", "situacion", "educacion", "tipo_hogar"]], drop_first=False, dtype=float)
    referencias = ["mercado_Partidos del GBA", "edad_30-39", "situacion_Asalariado formal",
                   "educacion_Secundario completo", "tipo_hogar_Pareja con hijos"]
    X = X.drop(columns=[c for c in referencias if c in X.columns])
    X["dos_o_mas_perceptores"] = d.dos_o_mas_perceptores
    X["jefatura_mujer"] = d.jefatura_mujer
    X = sm.add_constant(X)
    return X, d.y, d.peso, d.hogar_id


def _sandwich_cluster(X: np.ndarray, y: np.ndarray, w: np.ndarray, prob: np.ndarray, grupos: np.ndarray) -> np.ndarray:
    """Varianza robusta por conglomerado para un logit ponderado: B^-1 (suma_g u_g u_g') B^-1 * G/(G-1)."""
    bread = np.linalg.inv(X.T @ ((w * prob * (1 - prob))[:, None] * X))
    scores = (w * (y - prob))[:, None] * X
    codigos, _ = pd.factorize(grupos)
    u = np.zeros((codigos.max() + 1, X.shape[1]))
    np.add.at(u, codigos, scores)
    g = len(u)
    return bread @ (u.T @ u) @ bread * g / (g - 1)


def logit_ponderado(ev: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    X, y, w, grupos = preparar_modelo(ev)
    w_norm = (w * len(w) / w.sum()).to_numpy()
    modelo = sm.GLM(y, X, family=sm.families.Binomial(), var_weights=w_norm).fit()
    prob = modelo.predict(X).to_numpy()
    cov = _sandwich_cluster(X.to_numpy(), y.to_numpy(), w_norm, prob, grupos.to_numpy())
    se = np.sqrt(np.diag(cov))
    b = modelo.params.to_numpy()
    z = stats.norm.ppf(0.975)
    tabla = pd.DataFrame({
        "variable": modelo.params.index, "odds_ratio": np.exp(b),
        "or_ic95_inf": np.exp(b - z * se), "or_ic95_sup": np.exp(b + z * se), "p_valor": 2 * stats.norm.sf(np.abs(b / se)),
    })
    tabla = tabla[tabla.variable != "const"].sort_values("odds_ratio", ascending=False)
    y_bin = (y >= 0.5).astype(int)
    info = {"n_observaciones": int(len(y)), "n_hogares": int(grupos.nunique()), "positivos": int(y_bin.sum()),
            "auc_ponderado": roc_auc_score(y_bin, prob, sample_weight=w),
            "pseudo_r2_mcfadden": 1 - modelo.llf / modelo.llnull,
            "errores": "robustos por conglomerado (hogar)",
            "referencia": "GBA · 30-39 años · asalariado formal · secundario completo · pareja con hijos"}
    return tabla, info


# ---------------------------------------------------------------------------
# H7 (recuadro) · trabajos en el hogar
# ---------------------------------------------------------------------------
def clasificar_fuentes(h: pd.DataFrame) -> pd.DataFrame:
    d = h.copy()
    d["fuentes_trabajo"] = np.select([d.trabajos_en_el_hogar == 0, d.trabajos_en_el_hogar == 1],
                                     ["Sin trabajo en el hogar", "1 trabajo"], default="2 o más trabajos")
    d["detalle_trabajo"] = np.select(
        [d.trabajos_en_el_hogar == 0, d.trabajos_en_el_hogar == 1, d.personas_ocupadas == 1],
        ["Sin trabajo en el hogar", "1 persona con 1 trabajo", "1 persona con 2 o más trabajos"],
        default="2 o más personas trabajando")
    return d


def acceso_por_fuentes(h: pd.DataFrame, m: dict, p: Producto = Producto(), B: int = 500) -> pd.DataFrame:
    d = clasificar_fuentes(h)
    ev = evaluar(d, m, p)
    filas = []
    for variable in ["fuentes_trabajo", "detalle_trabajo"]:
        for grupo, sub in ev.groupby(variable):
            punto, lo, hi = bootstrap_evaluado(sub, "elegible", B=B, semilla=SEMILLA)
            filas.append({
                "variable": variable, "grupo": grupo, "muestra_hogares": sub.hogar_id.nunique(), "hogares": sub.peso.sum(),
                "pct_de_inquilinos": 100 * sub.peso.sum() / ev.peso.sum(),
                "ingreso_mediano": wquant(sub.ingreso, sub.peso),
                "pct_con_ingreso_demostrable": 100 * sub.peso[sub.hogar_formal.astype(bool)].sum() / sub.peso.sum(),
                "pct_pasan_cuota_y_anticipo": 100 * sub.peso[sub.pasa_cuota & sub.pasa_anticipo].sum() / sub.peso.sum(),
                "pct_elegible": punto, "ic95_inf": lo, "ic95_sup": hi, "hogares_elegibles": sub.peso[sub.elegible].sum(),
            })
    return pd.DataFrame(filas)


def escenario_solo_titulares(h: pd.DataFrame, m: dict, p: Producto = Producto()) -> dict:
    todo = evaluar(h, m, p)
    solo = evaluar(h.assign(ingreso=h.ingreso_titulares_ago26), m, p)
    e_todo, e_solo = todo.peso[todo.elegible].sum(), solo.peso[solo.elegible].sum()
    con_ingreso = h[h.ingreso > 0]
    return {"elegibles_ingreso_hogar": e_todo, "elegibles_solo_titulares": e_solo,
            "diferencia_hogares": e_todo - e_solo, "diferencia_pct": 100 * (e_solo / e_todo - 1),
            "pct_ingreso_de_otros_miembros": 100 * (1 - (con_ingreso.ingreso_titulares_ago26 * con_ingreso.peso).sum()
                                                    / (con_ingreso.ingreso * con_ingreso.peso).sum())}


# ---------------------------------------------------------------------------
# Segmentación de "casi elegibles"
# ---------------------------------------------------------------------------
def casi_elegibles(ev: pd.DataFrame, cobertura_min: float = 0.6) -> pd.DataFrame:
    """No elegibles cuyo ingreso cubre al menos el 60% del ingreso requerido (a un paso de calificar)."""
    d = ev[~ev.elegible].copy()
    d["cobertura_ingreso"] = d.ingreso / d.ingreso_requerido_ars
    return d[(d.cobertura_ingreso >= cobertura_min) & d.pasa_edad]


FEATURES = ["log_ingreso", "cobertura_ingreso", "jefe_edad", "miembros", "perceptores_ingreso", "hogar_formal"]


def segmentar(casi: pd.DataFrame, k_rango=range(3, 7), minimo_por_segmento: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    # Una fila por observación hogar-trimestre (las réplicas por partido se resumen con su cobertura promedio)
    d = (casi.groupby(["hogar_id", "periodo"])
         .agg(peso=("peso", "sum"), ingreso=("ingreso", "first"), cobertura_ingreso=("cobertura_ingreso", "mean"),
              jefe_edad=("jefe_edad", "first"), miembros=("miembros", "first"), perceptores_ingreso=("perceptores_ingreso", "first"),
              hogar_formal=("hogar_formal", "first"), mercado=("mercado", "first"), queda_afuera_en=("queda_afuera_en", "first"))
         .reset_index())
    d["log_ingreso"] = np.log(d.ingreso)
    d["hogar_formal"] = d.hogar_formal.astype(float)
    Xs = StandardScaler().fit_transform(d[FEATURES])
    sil, modelos, validos = {}, {}, []
    for k in k_rango:
        km = KMeans(n_clusters=k, n_init=25, random_state=SEMILLA).fit(Xs, sample_weight=d.peso)
        sil[k] = silhouette_score(Xs, km.labels_, random_state=SEMILLA)
        modelos[k] = km
        # Un segmento con menos de 30 hogares encuestados no es estable ni accionable
        if d.assign(s=km.labels_).groupby("s").hogar_id.nunique().min() >= minimo_por_segmento:
            validos.append(k)
    k_opt = max(validos or list(sil), key=sil.get)
    d["segmento"] = modelos[k_opt].labels_

    perfil = d.groupby("segmento").apply(lambda g: pd.Series({
        "hogares": g.peso.sum(),
        "muestra_hogares": g.hogar_id.nunique(),
        "ingreso_mediano": wquant(g.ingreso, g.peso),
        "cobertura_mediana": wquant(g.cobertura_ingreso, g.peso),
        "edad_mediana": wquant(g.jefe_edad, g.peso),
        "miembros_mediana": wquant(g.miembros, g.peso),
        "pct_formal": 100 * g.peso[g.hogar_formal == 1].sum() / g.peso.sum(),
        "pct_2_perceptores": 100 * g.peso[g.perceptores_ingreso >= 2].sum() / g.peso.sum(),
        "pct_caba": 100 * g.peso[g.mercado == "CABA"].sum() / g.peso.sum(),
        "pct_gba": 100 * g.peso[g.mercado == GBA].sum() / g.peso.sum(),
        "pct_falla_formal": 100 * g.peso[g.queda_afuera_en == "Ingreso demostrable"].sum() / g.peso.sum(),
    }), include_groups=False).sort_values("hogares", ascending=False)
    return d, perfil, {"k_optimo": k_opt, "silhouette": sil, "k_validos": validos}


# ---------------------------------------------------------------------------
# H5 complemento · ¿qué tan estable es el ingreso? (panel de la EPH: mismo hogar en dos trimestres seguidos)
# ---------------------------------------------------------------------------
def volatilidad_ingresos(con) -> pd.DataFrame:
    """Cambio del ingreso real entre dos visitas consecutivas, según la inserción laboral de jefe/a o cónyuge.

    Todas las tenencias (para tener muestra suficiente). Solo hogares que declararon ingreso en ambas visitas.
    """
    d = con.execute("""
        WITH v AS (
            SELECT hogar_id, periodo, anio * 4 + trimestre AS t, itf_real_ago26 AS ingreso, pondera_ajust AS peso,
                   CASE WHEN hogar_formal THEN 'Asalariado con aportes'
                        WHEN jefe_o_conyuge_indep_registrado THEN 'Independiente con aportes'
                        ELSE 'Sin aportes (informal o no ocupado)' END AS insercion
            FROM hogares_eph WHERE ingreso_declarado AND itf_real_ago26 > 0
        )
        SELECT a.hogar_id, a.insercion, a.peso, a.ingreso AS ingreso_1, b.ingreso AS ingreso_2
        FROM v a JOIN v b ON a.hogar_id = b.hogar_id AND b.t = a.t + 1
    """).df()
    d["cambio"] = d.ingreso_2 / d.ingreso_1 - 1
    filas = []
    for grupo, g in d.groupby("insercion"):
        filas.append({
            "insercion": grupo, "muestra_hogares": len(g),
            "cambio_absoluto_mediano_pct": 100 * wquant(g.cambio.abs(), g.peso),
            "pct_cae_mas_20": 100 * g.peso[g.cambio < -0.20].sum() / g.peso.sum(),
            "pct_sube_mas_20": 100 * g.peso[g.cambio > 0.20].sum() / g.peso.sum(),
        })
    return pd.DataFrame(filas)
