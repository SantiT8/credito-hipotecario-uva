"""No respuesta de ingresos: imputación múltiple como control de robustez.

Uso:  .venv\\Scripts\\python.exe src\\imputacion.py

La base del estudio usa PONDIH, el peso con el que el INDEC redistribuye a los hogares que no declararon
ingresos (DECIFR = 12) entre los que sí lo hicieron. Ese método supone que quien no responde se parece al
promedio de su estrato. Acá se prueba otro supuesto: que se parece a hogares con su misma estructura
laboral y demográfica. Si ambos métodos dan resultados parecidos, la conclusión no depende del método.

Método: predictive mean matching (PMM), m = 10 imputaciones.
  1. Donantes: hogares de los 3 mercados (cualquier tenencia) que declararon su ingreso.
  2. Modelo lineal ponderado de log(1 + ingreso) con covariables que la EPH releva aunque no haya
     respuesta de ingresos (ocupación, aportes, horas, educación, edad, tamaño, tenencia, mercado, trimestre).
  3. En cada imputación se reestiman los coeficientes sobre una muestra bootstrap de donantes y cada
     hogar sin respuesta recibe el ingreso observado de uno de los 5 donantes con predicción más cercana.
  4. Las estimaciones se combinan con las reglas de Rubin.
Validación: se ocultan ingresos conocidos de inquilinos, se imputan y se compara la elegibilidad.
Salida: data/processed/resultados/imputacion_no_respuesta.json
"""
import json

import duckdb
import numpy as np
import pandas as pd

from affordability import COLUMNAS_HOGAR, Producto, bootstrap_evaluado, evaluar, parametros_mercado
from config import DB_PATH, PROCESSED

M_IMPUTACIONES = 10
K_DONANTES = 5
SEMILLA = 2026


def cargar_hogares(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Todos los hogares (con y sin ingreso declarado) con covariables laborales agregadas por hogar."""
    columnas = COLUMNAS_HOGAR.replace("pondih_ajust AS peso", "pondera_ajust AS peso")
    return con.execute(f"""
        WITH ind AS (
            SELECT CODUSU AS codusu, CAST(NRO_HOGAR AS INT) AS nro_hogar, CAST(ANO4 AS INT) * 10 + CAST(TRIMESTRE AS INT) AS periodo,
                   CAST(ESTADO AS INT) AS estado, CAST(CAT_OCUP AS INT) AS cat_ocup, TRY_CAST(PP07H AS INT) AS pp07h,
                   TRY_CAST(PP05I AS INT) AS pp05i, TRY_CAST(CAT_INAC AS INT) AS cat_inac,
                   TRY_CAST(PP3E_TOT AS DOUBLE) AS h1, TRY_CAST(PP3F_TOT AS DOUBLE) AS h2
            FROM stg_eph_individual WHERE CAST(AGLOMERADO AS INT) IN (32, 33, 13)
        ), agg AS (
            SELECT codusu, nro_hogar, periodo,
                   count(*) FILTER (WHERE estado = 1 AND cat_ocup = 3 AND pp07h = 1) AS asalariados_formales,
                   count(*) FILTER (WHERE estado = 1 AND cat_ocup = 3 AND coalesce(pp07h, 0) <> 1) AS asalariados_informales,
                   count(*) FILTER (WHERE estado = 1 AND cat_ocup IN (1, 2) AND pp05i IN (1, 3)) AS independientes_con_aportes,
                   count(*) FILTER (WHERE estado = 1 AND cat_ocup IN (1, 2) AND coalesce(pp05i, 0) NOT IN (1, 3)) AS independientes_sin_aportes,
                   count(*) FILTER (WHERE estado = 2) AS desocupados,
                   count(*) FILTER (WHERE estado = 3 AND cat_inac = 1) AS jubilados,
                   -- 999 = no sabe / no responde
                   sum(CASE WHEN estado = 1 THEN least(CASE WHEN h1 BETWEEN 0 AND 168 THEN h1 ELSE 0 END
                                                 + CASE WHEN h2 BETWEEN 0 AND 168 THEN h2 ELSE 0 END, 120) END) AS horas_semanales
            FROM ind GROUP BY ALL
        )
        SELECT {columnas}, h.tenencia, h.ingreso_declarado, h.jefe_edad AS edad,
               agg.asalariados_formales, agg.asalariados_informales, agg.independientes_con_aportes,
               agg.independientes_sin_aportes, agg.desocupados, agg.jubilados, coalesce(agg.horas_semanales, 0) AS horas_semanales
        FROM hogares_eph h JOIN agg USING (codusu, nro_hogar, periodo)
        WHERE h.pondera_ajust > 0
        ORDER BY h.hogar_id, h.periodo
    """).df()


def matriz(d: pd.DataFrame, columnas: list[str] | None = None) -> pd.DataFrame:
    X = pd.DataFrame({
        "miembros": d.miembros.clip(upper=8), "edad": d.edad, "edad2": (d.edad / 10) ** 2,
        "mujer": (d.jefe_sexo == 2).astype(float), "conyuge": d.tiene_conyuge.astype(float),
        "asal_formales": d.asalariados_formales, "asal_informales": d.asalariados_informales,
        "indep_aportes": d.independientes_con_aportes, "indep_sin_aportes": d.independientes_sin_aportes,
        "desocupados": d.desocupados, "jubilados": d.jubilados, "horas": d.horas_semanales / 40,
        "trabajos": d.trabajos_en_el_hogar.clip(upper=6),
    })
    dummies = pd.get_dummies(d[["mercado", "tenencia", "periodo", "jefe_nivel_ed"]].astype(str), dtype=float)
    X = pd.concat([X, dummies], axis=1)
    X.insert(0, "const", 1.0)
    if columnas is not None:
        X = X.reindex(columns=columnas, fill_value=0.0)
    return X


def _ols_ponderado(X: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return beta


def imputar(donantes: pd.DataFrame, receptores: pd.DataFrame, rng: np.random.Generator, m: int = M_IMPUTACIONES) -> list[np.ndarray]:
    """Devuelve m vectores de ingreso imputado (uno por imputación) para los receptores."""
    Xd = matriz(donantes)
    cols = list(Xd.columns)
    Xr = matriz(receptores, cols).to_numpy()
    Xd = Xd.to_numpy()
    y = np.log1p(donantes.ingreso.clip(lower=0).to_numpy())
    w = donantes.peso.to_numpy()
    beta_hat = _ols_ponderado(Xd, y, w)
    pred_d = Xd @ beta_hat
    orden = np.argsort(pred_d)
    pred_ordenada = pred_d[orden]
    ingreso_ordenado = donantes.ingreso.to_numpy()[orden]
    salidas = []
    p = w / w.sum()
    for _ in range(m):
        idx = rng.choice(len(donantes), size=len(donantes), replace=True, p=p)
        beta_m = _ols_ponderado(Xd[idx], y[idx], np.ones(len(idx)))
        pred_r = Xr @ beta_m
        # K donantes más cercanos en la predicción (búsqueda sobre el vector ordenado)
        pos = np.searchsorted(pred_ordenada, pred_r)
        elegidos = np.empty(len(pred_r))
        for i, (pr, ps) in enumerate(zip(pred_r, pos)):
            lo, hi = max(ps - K_DONANTES, 0), min(ps + K_DONANTES, len(pred_ordenada))
            ventana = np.arange(lo, hi)
            cercanos = ventana[np.argsort(np.abs(pred_ordenada[ventana] - pr))[:K_DONANTES]]
            elegidos[i] = ingreso_ordenado[rng.choice(cercanos)]
        salidas.append(elegidos)
    return salidas


def rubin(estimaciones: list[float], varianzas: list[float]) -> dict:
    q = np.asarray(estimaciones)
    u = np.asarray(varianzas)
    m = len(q)
    q_bar, w_bar, b = q.mean(), u.mean(), q.var(ddof=1)
    t = w_bar + (1 + 1 / m) * b
    return {"estimacion": q_bar, "ic95_inf": q_bar - 1.96 * np.sqrt(t), "ic95_sup": q_bar + 1.96 * np.sqrt(t),
            "varianza_dentro": w_bar, "varianza_entre": b,
            "fraccion_info_faltante": (1 + 1 / m) * b / t if t > 0 else 0.0}


def _pct_y_var(ev: pd.DataFrame) -> tuple[float, float, float]:
    punto, lo, hi = bootstrap_evaluado(ev, "elegible", B=300, semilla=SEMILLA)
    se = (hi - lo) / (2 * 1.96)
    return punto, se ** 2, ev.peso[ev.elegible].sum()


def validar(hogares: pd.DataFrame, mercado: dict, rng: np.random.Generator, p: Producto, repeticiones: int = 5) -> pd.DataFrame:
    """Oculta el 30% de los ingresos de inquilinos que sí declararon, los imputa y compara la elegibilidad."""
    declarados = hogares[hogares.ingreso_declarado]
    inq = declarados[declarados.tenencia == "Inquilino"]
    filas = []
    for r in range(repeticiones):
        ocultos = inq.sample(frac=0.3, random_state=SEMILLA + r)
        donantes = declarados.drop(ocultos.index)
        imputado = imputar(donantes, ocultos, rng, m=1)[0]
        real = evaluar(ocultos, mercado, p)
        estimado = evaluar(ocultos.assign(ingreso=imputado), mercado, p)
        filas.append({"repeticion": r + 1, "hogares_ocultos": len(ocultos),
                      "pct_elegible_real": 100 * real.peso[real.elegible].sum() / real.peso.sum(),
                      "pct_elegible_imputado": 100 * estimado.peso[estimado.elegible].sum() / estimado.peso.sum(),
                      "mediana_ingreso_real": float(np.median(ocultos.ingreso)),
                      "mediana_ingreso_imputado": float(np.median(imputado))})
    return pd.DataFrame(filas)


def main(verbose: bool = True) -> dict:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    mercado = parametros_mercado(con)
    hogares = cargar_hogares(con)
    con.close()
    rng = np.random.default_rng(SEMILLA)
    p = Producto()

    donantes = hogares[hogares.ingreso_declarado]
    receptores = hogares[~hogares.ingreso_declarado & (hogares.tenencia == "Inquilino")]
    inquilinos_decl = donantes[donantes.tenencia == "Inquilino"]

    estimaciones, varianzas, absolutos, por_mercado = [], [], [], []
    for ingreso in imputar(donantes, receptores, rng):
        completos = pd.concat([inquilinos_decl, receptores.assign(ingreso=ingreso)], ignore_index=True)
        ev = evaluar(completos, mercado, p)
        pct, var, hog = _pct_y_var(ev)
        estimaciones.append(pct)
        varianzas.append(var)
        absolutos.append(hog)
        por_mercado.append(ev.groupby("mercado").apply(lambda g: 100 * g.peso[g.elegible].sum() / g.peso.sum(), include_groups=False))

    combinado = rubin(estimaciones, varianzas)
    validacion = validar(hogares, mercado, rng, p)
    resultado = {
        "metodo": "PMM, m=10, k=5 donantes; reglas de Rubin",
        "inquilinos_sin_ingreso_declarado_obs": int(len(receptores)),
        "inquilinos_sin_ingreso_declarado_hogares": float(receptores.peso.sum()),
        "pct_inquilinos_sin_ingreso_declarado": float(100 * receptores.peso.sum() / hogares[hogares.tenencia == "Inquilino"].peso.sum()),
        "pct_elegible_imputacion": combinado,
        "hogares_elegibles_imputacion": float(np.mean(absolutos)),
        "hogares_elegibles_imputacion_min": float(np.min(absolutos)),
        "hogares_elegibles_imputacion_max": float(np.max(absolutos)),
        "pct_elegible_por_mercado_imputacion": pd.concat(por_mercado, axis=1).mean(axis=1).to_dict(),
        "validacion": {
            "repeticiones": len(validacion),
            "pct_elegible_real_promedio": float(validacion.pct_elegible_real.mean()),
            "pct_elegible_imputado_promedio": float(validacion.pct_elegible_imputado.mean()),
            "error_absoluto_medio_pp": float((validacion.pct_elegible_imputado - validacion.pct_elegible_real).abs().mean()),
            "detalle": validacion.to_dict(orient="records"),
        },
    }
    salida = PROCESSED / "resultados" / "imputacion_no_respuesta.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    if verbose:
        print(json.dumps(resultado, indent=2, ensure_ascii=False, default=float))
    return resultado


if __name__ == "__main__":
    main()
