"""Motor de elegibilidad hipotecaria UVA: una sola implementación para análisis, dashboard, documentos y deck.

Cada hogar inquilino pasa por el embudo validado:
  1. cuota inicial <= tope de cuota/ingreso
  2. anticipo + gastos <= N ingresos mensuales
  3. ingreso demostrable (base: jefe/a o cónyuge asalariado con aportes)
  4. edad del jefe/a + plazo <= edad máxima al terminar el crédito

GBA abierto: la EPH no identifica partido, así que cada hogar inquilino del GBA se evalúa en la grilla
de 31 partidos del aglomerado, con el precio Zonaprop de cada partido y un peso proporcional a los
hogares inquilinos de ese partido según el Censo 2022. El total del GBA conserva el peso original del
hogar; lo que se reparte es "dónde podría buscar vivienda". Supuesto declarado: la distribución de
ingresos de los inquilinos del GBA es la misma en todos los partidos (la EPH no permite observarla).
"""
from dataclasses import dataclass, replace

import duckdb
import numpy as np
import pandas as pd

from config import BASE, FECHA_CORTE, m2_por_hogar

ETAPAS = ["Inquilinos", "Pagan la cuota", "Juntan el anticipo", "Ingreso demostrable", "Cumplen la edad"]
GBA = "Partidos del GBA"


@dataclass(frozen=True)
class Producto:
    tna: float = BASE["tna"]
    plazo_anios: int = BASE["plazo_anios"]
    ltv: float = BASE["ltv"]
    tope_cuota_ingreso: float = BASE["tope_cuota_ingreso"]
    gastos_compra: float = BASE["gastos_compra"]
    tope_prestamo_uva: float = BASE["tope_prestamo_uva"]
    meses_ingreso_anticipo: float = BASE["meses_ingreso_anticipo"]
    requiere_ingreso_formal: bool = BASE["requiere_ingreso_formal"]
    acepta_independientes: bool = False  # módulo aparte: monotributo/autónomos cuentan como ingreso demostrable
    edad_max_fin_credito: int = BASE["edad_max_fin_credito"]
    factor_precio: float = 1.0           # sensibilidad de precios
    m2_fijo: int | None = None           # H1: todos los hogares buscan la misma superficie

    def con(self, **cambios) -> "Producto":
        return replace(self, **cambios)


def factor_cuota(tna: float, plazo_anios: int) -> float:
    """Cuota mensual por cada peso prestado (sistema francés, tasa mensual = TNA/12)."""
    r, n = tna / 12, plazo_anios * 12
    return 1 / n if r == 0 else r / (1 - (1 + r) ** -n)


def parametros_mercado(con: duckdb.DuckDBPyConnection) -> dict:
    """UVA y dólar minorista a la fecha de corte, precios por mercado y grilla de partidos del GBA."""
    uva, fecha_uva = con.execute(
        "SELECT CAST(valor AS DOUBLE), CAST(fecha AS DATE) FROM stg_bcra WHERE serie = 'uva' AND CAST(fecha AS DATE) <= ? "
        "ORDER BY CAST(fecha AS DATE) DESC LIMIT 1", [FECHA_CORTE]).fetchone()
    tc, fecha_tc = con.execute(
        "SELECT CAST(valor AS DOUBLE), CAST(fecha AS DATE) FROM stg_bcra WHERE serie = 'tipo_cambio_minorista' AND CAST(fecha AS DATE) <= ? "
        "ORDER BY CAST(fecha AS DATE) DESC LIMIT 1", [FECHA_CORTE]).fetchone()
    precios = dict(con.execute("SELECT mercado, usd_m2 FROM ref_precios_mercado").fetchall())
    gba = con.execute("SELECT partido, corredor, usd_m2, peso_en_gba, peso_en_corredor, precio_imputado_por_corredor "
                      "FROM ref_precios_gba_partido ORDER BY corredor, partido").df()
    return {"uva": uva, "fecha_uva": fecha_uva, "tc": tc, "fecha_tc": fecha_tc, "usd_m2": precios, "gba_partidos": gba}


COLUMNAS_HOGAR = """
    hogar_id, codusu, nro_hogar, periodo, mercado, miembros, itf_real_ago26 AS ingreso, pondih_ajust AS peso,
    ingreso_titulares_ago26, ingreso_asalariado_formal_ago26, ingreso_por_persona_ago26, ingreso_por_perceptor_ago26,
    jefe_edad, jefe_sexo, jefe_nivel_ed, jefe_situacion_laboral, tiene_conyuge, hogar_formal,
    jefe_o_conyuge_indep_registrado, jefe_o_conyuge_monotributo_social,
    perceptores_ingreso, tramo_edad_jefe, personas_ocupadas, personas_con_mas_de_un_trabajo,
    trabajos_en_el_hogar, tiene_ingreso_no_laboral, tipo_hogar, hijos
"""


def cargar_inquilinos(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Observaciones hogar-trimestre de inquilinos con ingreso declarado (PONDIH > 0: la no respuesta ya está redistribuida)."""
    return con.execute(f"""
        SELECT {COLUMNAS_HOGAR}
        FROM hogares_eph
        WHERE tenencia = 'Inquilino' AND ingreso_declarado AND pondih_ajust > 0
        ORDER BY hogar_id, periodo          -- orden fijo: resultados reproducibles con la misma semilla
    """).df()


def expandir_gba(h: pd.DataFrame, mercado: dict, corredor: str | None = None) -> pd.DataFrame:
    """Replica cada hogar del GBA en la grilla de partidos (todo el GBA o un solo corredor), repartiendo su peso."""
    gba = mercado["gba_partidos"]
    if corredor is not None:
        gba = gba[gba.corredor == corredor].assign(w=lambda d: d.peso_en_corredor)
    else:
        gba = gba.assign(w=lambda d: d.peso_en_gba)
    resto = h[h.mercado != GBA].assign(partido=pd.NA, corredor=pd.NA)
    resto["usd_m2"] = resto.mercado.map(mercado["usd_m2"])
    g = h[h.mercado == GBA].merge(gba[["partido", "corredor", "usd_m2", "w"]], how="cross")
    g["peso"] = g.peso * g.w
    return pd.concat([resto, g.drop(columns="w")], ignore_index=True)


def evaluar(hogares: pd.DataFrame, mercado: dict, p: Producto = Producto(), corredor_gba: str | None = None) -> pd.DataFrame:
    """Aplica el embudo a cada hogar (y a cada partido del GBA). Devuelve montos, ratios y la etapa donde queda afuera."""
    h = expandir_gba(hogares, mercado, corredor_gba)
    h["m2"] = p.m2_fijo if p.m2_fijo is not None else h.miembros.map(m2_por_hogar)
    h["precio_usd"] = h.usd_m2 * h.m2 * p.factor_precio
    h["precio_ars"] = h.precio_usd * mercado["tc"]
    h["prestamo_ars"] = np.minimum(p.ltv * h.precio_ars, p.tope_prestamo_uva * mercado["uva"])
    h["cuota_ars"] = h.prestamo_ars * factor_cuota(p.tna, p.plazo_anios)
    h["efectivo_necesario_ars"] = (h.precio_ars - h.prestamo_ars) + p.gastos_compra * h.precio_ars
    ingreso = h.ingreso.where(h.ingreso > 0)
    h["ratio_cuota_ingreso"] = (h.cuota_ars / ingreso).fillna(np.inf)
    h["ingresos_de_efectivo"] = (h.efectivo_necesario_ars / ingreso).fillna(np.inf)
    h["ingreso_requerido_ars"] = np.maximum(h.cuota_ars / p.tope_cuota_ingreso, h.efectivo_necesario_ars / p.meses_ingreso_anticipo)

    h["pasa_cuota"] = h.ratio_cuota_ingreso <= p.tope_cuota_ingreso
    h["pasa_anticipo"] = h.ingresos_de_efectivo <= p.meses_ingreso_anticipo
    if not p.requiere_ingreso_formal:
        h["pasa_formal"] = True
    elif p.acepta_independientes:
        h["pasa_formal"] = h.hogar_formal.astype(bool) | h.jefe_o_conyuge_indep_registrado.astype(bool)
    else:
        h["pasa_formal"] = h.hogar_formal.astype(bool)
    h["pasa_edad"] = (h.jefe_edad + p.plazo_anios) <= p.edad_max_fin_credito

    h["queda_afuera_en"] = np.select(
        [~h.pasa_cuota, ~h.pasa_anticipo, ~h.pasa_formal, ~h.pasa_edad],
        ["Pagan la cuota", "Juntan el anticipo", "Ingreso demostrable", "Cumplen la edad"],
        default="Elegible")
    h["elegible"] = h.queda_afuera_en == "Elegible"
    return h


def embudo(evaluado: pd.DataFrame, por: str | None = None) -> pd.DataFrame:
    """Hogares expandidos que sobreviven a cada etapa (acumulado), total o por grupo."""
    def _uno(d: pd.DataFrame) -> pd.DataFrame:
        w = d.peso
        mascaras = [np.ones(len(d), bool), d.pasa_cuota, d.pasa_cuota & d.pasa_anticipo,
                    d.pasa_cuota & d.pasa_anticipo & d.pasa_formal, d.elegible]
        vivos = [w[mk].sum() for mk in mascaras]
        out = pd.DataFrame({"etapa": ETAPAS, "hogares": vivos})
        out["pct_del_total"] = 100 * out.hogares / vivos[0]
        out["pct_de_etapa_anterior"] = 100 * out.hogares / out.hogares.shift(1).fillna(vivos[0])
        out["muestra_hogares"] = [d.loc[mk, "hogar_id"].nunique() for mk in mascaras]
        return out

    if por is None:
        return _uno(evaluado)
    return pd.concat([_uno(g).assign(**{por: k}) for k, g in evaluado.groupby(por, dropna=True)], ignore_index=True)


def pct_elegible(evaluado: pd.DataFrame) -> float:
    return 100 * evaluado.peso[evaluado.elegible].sum() / evaluado.peso.sum()


def bootstrap_evaluado(ev: pd.DataFrame, columna: str = "elegible", B: int = 1000, semilla: int = 2026) -> tuple[float, float, float]:
    """IC 95% por bootstrap de conglomerados: se remuestrean HOGARES (todas sus visitas y réplicas juntas), por mercado.

    Aproximado: la base usuaria de la EPH no publica los conglomerados ni estratos del diseño muestral,
    así que el IC no incorpora ese efecto (probablemente es algo más angosto que el real).
    """
    flag = ev[columna].to_numpy(dtype=float)
    d = pd.DataFrame({"hogar_id": ev.hogar_id.to_numpy(), "mercado": ev.mercado.to_numpy(),
                      "w": ev.peso.to_numpy(), "wf": ev.peso.to_numpy() * flag})
    por_hogar = d.groupby(["mercado", "hogar_id"], sort=False)[["w", "wf"]].sum().reset_index()
    rng = np.random.default_rng(semilla)
    num, den = np.zeros(B), np.zeros(B)
    for _, grupo in por_hogar.groupby("mercado"):
        w, wf = grupo.w.to_numpy(), grupo.wf.to_numpy()
        conteos = rng.multinomial(len(grupo), np.full(len(grupo), 1 / len(grupo)), size=B)  # B × hogares
        num += conteos @ wf
        den += conteos @ w
    stats = 100 * num / den
    punto = 100 * d.wf.sum() / d.w.sum()
    return punto, float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def bootstrap_pct(hogares: pd.DataFrame, mercado: dict, p: Producto, columna: str = "elegible",
                  B: int = 1000, semilla: int = 2026, corredor_gba: str | None = None) -> tuple[float, float, float]:
    return bootstrap_evaluado(evaluar(hogares, mercado, p, corredor_gba), columna, B, semilla)
