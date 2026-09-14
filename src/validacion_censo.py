"""Validación externa del universo EPH contra el Censo 2022 (INDEC, resultados definitivos).

Uso:  .venv\\Scripts\\python.exe src\\validacion_censo.py

Compara, por zona: hogares totales y distribución por régimen de tenencia. Con eso arma un rango
"ajustado al Censo" para las cifras absolutas (la EPH capta algo menos de inquilinos que el Censo).
Salidas: data/processed/evidencia/validacion_censo/comparacion_eph_censo.csv y resumen.json

Notas de geografía (no hay equivalencia perfecta):
- CABA: idéntica en ambas fuentes.
- EPH "Partidos del GBA" es el aglomerado urbano: los 24 partidos + partes de Cañuelas, Escobar,
  Gral. Rodríguez, Marcos Paz, Pilar, Pte. Perón y San Vicente. Se muestran los dos agregados
  que publica el INDEC: 24 partidos (piso) y 31 partidos (techo).
- Gran Córdoba excede el departamento Capital (incluye localidades vecinas): el Censo por departamento es un piso.
- Las fechas difieren: Censo mayo-2022; EPH 2T-2025 a 1T-2026.
"""
import json

import duckdb
import pandas as pd

from config import DB_PATH, PROCESSED

GEOGRAFIAS = [
    ("CABA", "CABA", "provincia", "02"),
    ("Partidos del GBA", "24 partidos", "agregado", "24P"),
    ("Partidos del GBA", "31 partidos", "agregado", "31P"),
    ("Gran Córdoba", "Depto. Capital", "departamento", "14014"),
    ("Total del país", "País", "pais", "Total"),
]


def censo(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    filas = []
    for zona, geo, nivel, codigo in GEOGRAFIAS:
        r = con.execute("SELECT * FROM stg_censo_hogares WHERE nivel = ? AND codigo = ?", [nivel, codigo]).df()
        if len(r) != 1:
            raise ValueError(f"No se encontró una única fila del Censo para {geo}")
        r = r.iloc[0]
        filas.append({"zona": zona, "geografia_censo": geo, "hogares_censo": r.hogares,
                      "pct_propia_censo": 100 * r.propia / r.hogares, "pct_alquilada_censo": 100 * r.alquilada / r.hogares,
                      "pct_otra_censo": 100 * (r.cedida_trabajo + r.prestada + r.otra) / r.hogares,
                      "hogares_alquilados_censo": r.alquilada})
    return pd.DataFrame(filas)


def eph(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Pool de 4 trimestres: cada trimestre expande a la población, así que se divide por 4
    return con.execute("""
        SELECT mercado AS zona,
               sum(pondera_ajust) AS hogares_eph,
               100 * sum(pondera_ajust) FILTER (WHERE tenencia = 'Propietario') / sum(pondera_ajust) AS pct_propia_eph,
               100 * sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino') / sum(pondera_ajust) AS pct_alquilada_eph,
               100 * sum(pondera_ajust) FILTER (WHERE tenencia NOT IN ('Propietario', 'Inquilino')) / sum(pondera_ajust) AS pct_otra_eph,
               sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino') AS hogares_alquilados_eph
        FROM hogares_eph GROUP BY 1
    """).df()


def main(verbose: bool = True, con: duckdb.DuckDBPyConnection | None = None) -> dict:
    propia = con is None
    con = duckdb.connect(str(DB_PATH), read_only=True) if propia else con
    comp = censo(con).merge(eph(con), on="zona", how="left")
    if propia:
        con.close()
    comp["dif_hogares_pct"] = 100 * (comp.hogares_eph / comp.hogares_censo - 1)
    comp["dif_alquila_pp"] = comp.pct_alquilada_eph - comp.pct_alquilada_censo

    # Rango ajustado: cuántos inquilinos habría si la EPH los captara como el Censo. El factor se aplica a las
    # cifras absolutas (hogares elegibles); los porcentajes no cambian.
    e = comp.dropna(subset=["hogares_eph"])
    inq_eph = e.drop_duplicates("zona").hogares_alquilados_eph.sum()

    def inquilinos_censo_pct(geo_gba: str) -> float:
        sel = e[e.geografia_censo.isin(["CABA", geo_gba, "Depto. Capital"])]
        return (sel.hogares_eph * sel.pct_alquilada_censo / 100).sum()

    inq_24, inq_31 = inquilinos_censo_pct("24 partidos"), inquilinos_censo_pct("31 partidos")
    alq_24 = comp[comp.geografia_censo.isin(["CABA", "24 partidos", "Depto. Capital"])].hogares_alquilados_censo.sum()
    alq_31 = comp[comp.geografia_censo.isin(["CABA", "31 partidos", "Depto. Capital"])].hogares_alquilados_censo.sum()
    # Dos lecturas del Censo: su % de inquilinos sobre los hogares EPH, o sus hogares alquilados en valor absoluto
    factores = sorted([inq_24 / inq_eph, inq_31 / inq_eph, alq_24 / inq_eph, alq_31 / inq_eph])
    factores = [factores[0], factores[-1]]
    resumen = {
        "inquilinos_eph": inq_eph,
        "hogares_eph_3_mercados": e.drop_duplicates("zona").hogares_eph.sum(),
        "pct_inquilinos_eph": 100 * inq_eph / e.drop_duplicates("zona").hogares_eph.sum(),
        "inquilinos_con_pct_censo_24p": inq_24, "inquilinos_con_pct_censo_31p": inq_31,
        "factor_ajuste_min": factores[0], "factor_ajuste_max": factores[1],
        "hogares_censo_24p": comp[comp.geografia_censo.isin(["CABA", "24 partidos", "Depto. Capital"])].hogares_censo.sum(),
        "hogares_censo_31p": comp[comp.geografia_censo.isin(["CABA", "31 partidos", "Depto. Capital"])].hogares_censo.sum(),
        "alquilados_censo_24p": alq_24, "alquilados_censo_31p": alq_31,
        "pct_propia_pais_censo": float(comp[comp.zona == "Total del país"].pct_propia_censo.iloc[0]),
        "pct_alquilada_pais_censo": float(comp[comp.zona == "Total del país"].pct_alquilada_censo.iloc[0]),
        "hogares_pais_censo": float(comp[comp.zona == "Total del país"].hogares_censo.iloc[0]),
    }

    out = PROCESSED / "evidencia" / "validacion_censo"
    out.mkdir(parents=True, exist_ok=True)
    comp.to_csv(out / "comparacion_eph_censo.csv", index=False)
    (out / "resumen.json").write_text(json.dumps(resumen, indent=2, default=float), encoding="utf-8")
    if verbose:
        pd.set_option("display.width", 220)
        print(comp.round(1).to_string(index=False))
        print({k: round(v, 3) for k, v in resumen.items()})
    return resumen


if __name__ == "__main__":
    main()
