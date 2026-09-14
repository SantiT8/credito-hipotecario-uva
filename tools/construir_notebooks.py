"""Construye los notebooks 01-05 del proyecto (después se ejecutan con nbconvert).

Uso:
    .venv\\Scripts\\python.exe tools\\construir_notebooks.py
    .venv\\Scripts\\jupyter nbconvert --to notebook --execute --inplace notebooks\\0*.ipynb

Los textos de lectura toman las cifras de data/processed/resultados/kpis.json con la regla única de
formato (src/formato.py): si cambian los datos, se regeneran y el relato no queda desactualizado.
"""
import json
import sys
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from formato import fmt_cantidad as C, fmt_decimal as D, fmt_hogares as H, fmt_monto as M, fmt_pct as P  # noqa: E402

NB_DIR = ROOT / "notebooks"
K = json.loads((ROOT / "data" / "processed" / "resultados" / "kpis.json").read_text(encoding="utf-8"))
EV = ROOT / "data" / "processed" / "evidencia"


def md(s: str):
    return nbf.v4.new_markdown_cell(s.strip())


def code(s: str):
    return nbf.v4.new_code_cell(s.strip())


def notebook(cells):
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    nb.cells = cells
    return nb


def uno_de_cada(pct: float) -> str:
    return f"1 de cada {round(100 / pct)}"


BASE_SQL = r'''
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "src"))

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

import config
import viz
from formato import fmt_cantidad, fmt_hogares, fmt_mes, fmt_monto, fmt_pct, fmt_decimal
from run_sql import run_file

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 30)
'''

BASE_ANALISIS = r'''
import sys, json, warnings
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "src"))
warnings.filterwarnings("ignore")

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

import config
import viz
import analysis as A
from affordability import ETAPAS, GBA, Producto, cargar_inquilinos, embudo, evaluar, parametros_mercado
from formato import fmt_cantidad, fmt_hogares, fmt_mes, fmt_monto, fmt_pct, fmt_decimal

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 30)

con = duckdb.connect(str(config.DB_PATH), read_only=True)
m = parametros_mercado(con)
h = cargar_inquilinos(con)
base = Producto()
ev = evaluar(h, m, base)
ev["zona"] = A.grupo_geografico(ev)
K = json.loads((config.PROCESSED / "resultados" / "kpis.json").read_text(encoding="utf-8"))
RAMPA = LinearSegmentedColormap.from_list("azul", ["#eef4fc"] + viz.BLUE_RAMP)

def tinta_sobre(valor, vmin, vmax):
    """Texto blanco sobre celdas oscuras y tinta sobre celdas claras (según luminancia del color de fondo)."""
    r, g, b, _ = RAMPA((valor - vmin) / (vmax - vmin))
    return "#ffffff" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45 else viz.INK
print(f"UVA ${m['uva']:,.2f} ({m['fecha_uva']}) · dólar minorista ${m['tc']:,.2f} ({m['fecha_tc']})")
print(f"Inquilinos con ingreso declarado: {len(h)} observaciones de {h.hogar_id.nunique()} hogares encuestados · representan {fmt_hogares(h.peso.sum())}")
'''


# ---------------------------------------------------------------------------
# 01 · Exploración
# ---------------------------------------------------------------------------
def nb01():
    import pandas as pd
    nr = pd.read_csv(EV / "02_profiling" / "eph_no_respuesta_ingresos.csv")
    pct_nr = float(nr.loc[nr.situacion.str.startswith("No respuesta"), "pct"].iloc[0])
    return notebook([
        md(f"""
# 01 · Exploración inicial: ¿qué tenemos entre manos?

**Proyecto:** ¿Quién puede pagar hoy un crédito hipotecario UVA? · **Rol:** analista de crédito y negocio · **Cliente (ficticio):** Banco [EMPRESA]

Antes de limpiar, miramos los datos **tal como vienen**, con las tres preguntas de negocio del encuadre (`reports/00_encuadre.md`):

1. ¿Cuántos hogares inquilinos hay en CABA, Partidos del GBA y Gran Córdoba, y cuánto ganan? → tamaño del mercado potencial.
2. ¿Cómo viene el mercado de crédito (tasa y stock)? → contexto de la decisión.
3. ¿Qué tan confiables son las fuentes de precios? → cuánto podemos apoyarnos en ellas.

> **Alcance (decisión del Checkpoint 3):** Gran Rosario quedó fuera por tamaño de muestra; el GBA se analiza abierto por corredor en los notebooks siguientes.

Este notebook carga las fuentes crudas en DuckDB (`sql/01_staging.sql`) y explora. Las decisiones de limpieza se toman en el notebook 02.
"""),
        code(BASE_SQL),
        md("## 0. Carga cruda a staging (SQL)"),
        code('''import os
os.chdir(config.ROOT)
con = duckdb.connect(str(config.DB_PATH))
run_file(con, config.ROOT / "sql" / "01_staging.sql")'''),
        md("""
## 1. EPH: hogares, tenencia e ingresos (datos crudos)

La EPH es una **encuesta**: cada hogar encuestado representa a muchos otros según su ponderador (`PONDERA` para hogares, `PONDIH` para ingresos). Explorar sin ponderar sobrerrepresenta a los aglomerados chicos, así que desde el inicio se pondera. Como se juntan 4 trimestres, cada peso se divide por 4: el resultado es el promedio del año.
"""),
        code(r'''tenencia = con.execute("""
    SELECT CASE AGLOMERADO WHEN '32' THEN 'CABA' WHEN '33' THEN 'Partidos del GBA' WHEN '13' THEN 'Gran Córdoba' END AS mercado,
           CASE WHEN II7 IN ('1','2') THEN 'Propietario' WHEN II7 = '3' THEN 'Inquilino' ELSE 'Otra situación' END AS tenencia,
           sum(CAST(PONDERA AS DOUBLE)) / 4 AS hogares
    FROM stg_eph_hogar
    WHERE AGLOMERADO IN ('32','33','13')
    GROUP BY ALL
""").df()
pivot = tenencia.pivot_table(index="mercado", columns="tenencia", values="hogares", aggfunc="sum")
pct = (pivot.div(pivot.sum(axis=1), axis=0) * 100).round(1)
pd.concat([pivot.map(fmt_cantidad), pct.add_suffix(" %")], axis=1).sort_values("Inquilino %", ascending=False)'''),
        code(r'''# % de hogares inquilinos por mercado: una sola serie, un solo color, ordenado por magnitud
s = pct["Inquilino"].sort_values()
fig, ax = plt.subplots(figsize=(7, 2.8))
bars = ax.barh(s.index, s.values, color=viz.BLUE, height=0.55)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.xaxis.set_major_formatter(viz.EJE_PCT)
for b, v in zip(bars, s.values):
    ax.text(v + 0.6, b.get_y() + b.get_height() / 2, fmt_pct(v), va="center", color=viz.INK_2, fontsize=9)
ax.set_xlim(0, s.max() * 1.18)
ax.set_title("En CABA, 1 de cada 3 hogares alquila")
viz.subtitle(ax, "Hogares inquilinos sobre el total · promedio 2T-2025 a 1T-2026 · datos crudos ponderados")
viz.source(fig, "INDEC, EPH microdatos.")
viz.save(fig, "01_pct_inquilinos_mercado")
plt.show()'''),
        md(f"""
**Primera señal de suciedad:** en el país, el {P(pct_nr)} de los hogares encuestados no declara su ingreso (decil 12, `ITF = 0`). Si se promediara el ingreso "a lo bruto", esos ceros bajarían artificialmente el resultado:
"""),
        code(r'''itf = con.execute("""
    SELECT CASE WHEN II7 = '3' THEN 'Inquilino' WHEN II7 IN ('1','2') THEN 'Propietario' ELSE 'Otra' END AS tenencia,
           CAST(ITF AS DOUBLE) AS itf, CAST(PONDERA AS DOUBLE) AS pondera, CAST(PONDIH AS DOUBLE) AS pondih
    FROM stg_eph_hogar
    WHERE AGLOMERADO IN ('32','33','13') AND ANO4 = '2026' AND TRIMESTRE = '1'
""").df()

def wmedian(x, w):
    o = np.argsort(x); x, w = np.asarray(x)[o], np.asarray(w)[o]
    return x[np.searchsorted(np.cumsum(w), w.sum() / 2)]

pd.DataFrame({
    "Mediana ingenua (todas las filas, PONDERA)": itf.groupby("tenencia").apply(lambda d: wmedian(d.itf, d.pondera), include_groups=False),
    "Mediana correcta (PONDIH, sin no respuesta)": itf[itf.pondih > 0].groupby("tenencia").apply(lambda d: wmedian(d.itf, d.pondih), include_groups=False),
}).map(lambda v: fmt_monto(v))'''),
        md("""
## 2. Mercado de crédito (BCRA): tasa y stock

Dos medidas de escala distinta → **dos gráficos**, nunca un doble eje (el doble eje inventa correlaciones).
"""),
        code(r'''bcra = con.execute("""
    SELECT serie, CAST(fecha AS DATE) AS fecha, CAST(valor AS DOUBLE) AS valor FROM stg_bcra
    WHERE serie IN ('tasa_hipotecaria_uva', 'stock_hipotecarios_personas_humanas', 'inflacion_mensual')
""").df()
tasa = bcra[bcra.serie == "tasa_hipotecaria_uva"].set_index("fecha").valor.sort_index()
stock = bcra[bcra.serie == "stock_hipotecarios_personas_humanas"].set_index("fecha").valor.sort_index()
infl = bcra[bcra.serie == "inflacion_mensual"].set_index("fecha").valor.sort_index()
ipc = (1 + infl / 100).cumprod()
stock_real = stock * 1e6 * ipc.iloc[-1] / ipc.reindex(stock.index, method="nearest")   # la serie viene en millones de ARS

fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
ax = axes[0]
ax.plot(tasa.index, tasa.values, color=viz.BLUE)
ax.set_title("Tasa de hipotecarios UVA (TNA %)")
viz.subtitle(ax, "Promedio mensual del sistema")
ax.annotate(fmt_pct(tasa.iloc[-1], 2), (tasa.index[-1], tasa.iloc[-1]), xytext=(4, 0), textcoords="offset points", color=viz.INK_2, fontsize=9, va="center")
ax = axes[1]
s = stock_real[stock_real.index >= "2010-01-01"]
ax.plot(s.index, s.values, color=viz.BLUE)
ax.set_title("Stock real de hipotecarios a personas")
viz.subtitle(ax, "Pesos de la última inflación publicada")
ax.yaxis.set_major_formatter(viz.EJE_CANTIDAD)
viz.source(fig, "BCRA, API de Estadísticas v4.0 (series 1240, 916, 27).")
fig.tight_layout()
viz.save(fig, "01_bcra_tasa_stock_crudo")
plt.show()'''),
        md("""
## 3. Avisos de departamentos (GCBA 2001-2020): ¿qué tan confiables?

El mismo dataset cambió **cinco veces de esquema** en 20 años y el volumen de avisos salta de ~4 mil a más de 150 mil. Un salto así casi nunca es "más mercado": suele ser un cambio en cómo se recolectan los datos (portales, capturas mensuales repetidas).
"""),
        code(r'''gcba = con.execute(r"""
    SELECT CAST(regexp_extract(filename, '(\d{4})') AS INT) AS anio, count(*) AS n FROM stg_gcba_2001_2014 GROUP BY 1
    UNION ALL SELECT 2015, count(*) FROM stg_gcba_2015
    UNION ALL SELECT 2016, count(*) FROM stg_gcba_2016
    UNION ALL SELECT 2017, count(*) FROM stg_gcba_2017
    UNION ALL SELECT 2018, count(*) FROM stg_gcba_2018
    UNION ALL SELECT 2019, count(*) FROM stg_gcba_2019
    UNION ALL SELECT 2020, count(*) FROM stg_gcba_2020
""").df().sort_values("anio")
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.bar(gcba.anio.astype(str), gcba.n, color=viz.BLUE, width=0.7)
ax.yaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.set_title("Avisos por año en el dataset crudo: el volumen se multiplica desde 2017")
viz.subtitle(ax, "Departamentos en venta publicados · sin limpiar · el salto coincide con cambios de esquema y capturas repetidas")
viz.source(fig, "GCBA, Departamentos en venta 2001-2020.")
viz.save(fig, "01_gcba_avisos_crudos_por_anio")
plt.show()'''),
        md(f"""
## Qué nos llevamos de la exploración

| Observación | Implicancia para la limpieza (notebook 02) |
|---|---|
| {P(pct_nr, 0)} de hogares sin ingreso declarado (decil 12) | Usar `PONDIH` para ingresos; nunca promediar el ITF crudo. Probar además una imputación como control |
| Los hogares se repiten entre trimestres (panel rotativo) | Apilar los 4 trimestres con pesos / 4 y tratar las visitas de un mismo hogar como un conglomerado |
| Ingresos de trimestres distintos en pesos corrientes | Llevar todo a pesos de agosto de 2026 con el IPC |
| Tasa UVA en alza en 2026; stock real creciendo desde 2024 | Contexto de mercado (se analiza con series limpias) |
| GCBA: 5 esquemas, volumen que explota desde 2017 | Armonizar columnas, deduplicar, filtrar tipos y valores extremos antes de usar precios |
"""),
        code("con.close()"),
    ])


# ---------------------------------------------------------------------------
# 02 · Limpieza y calidad
# ---------------------------------------------------------------------------
def nb02():
    c = K["universo"]["censo"]
    return notebook([
        md("""
# 02 · Perfilado, limpieza y validación de calidad

Objetivo: pasar de staging (datos "como vienen") a **tablas limpias y confiables**, dejando evidencia de **cada** decisión.

- `sql/02_profiling.sql` → mide los problemas (cada consulta queda guardada en `data/processed/evidencia/`)
- `sql/03_clean.sql` → aplica las reglas y valida el resultado
- `sql/04_marts.sql` → series agregadas para el análisis
- Resumen de decisiones: `reports/01_calidad_datos.md`

> Regla del proyecto: ninguna fila se descarta en silencio. Todo filtro tiene un conteo y una justificación.
"""),
        code(BASE_SQL),
        code('''import os
os.chdir(config.ROOT)
con = duckdb.connect(str(config.DB_PATH))
run_file(con, config.ROOT / "sql" / "02_profiling.sql")'''),
        code('''EV = config.PROCESSED / "evidencia"
def ev(carpeta, nombre):
    return pd.read_csv(EV / carpeta / f"{nombre}.csv")'''),
        md("""
## 1. EPH: problemas encontrados

### 1.1 El panel rotativo repite hogares
La EPH entrevista a cada vivienda 2 trimestres, la deja 2 y vuelve 2. Al juntar 4 trimestres, **más de la mitad de los hogares aparece dos veces**.

> **Decisión y corrección (Checkpoint 3).** La primera versión se quedaba con la visita más reciente de cada hogar. Al revisar la cantidad de inquilinos contra el Censo 2022 apareció un sesgo: los inquilinos se mudan más, aparecen una sola vez con más frecuencia y quedaban sobrerrepresentados. Se cambió a un **pool**: se apilan los 4 trimestres (cada uno es una muestra representativa) y cada peso se divide por 4. Los márgenes de error tratan las visitas de un mismo hogar como un conglomerado.
"""),
        code('ev("02_profiling", "eph_panel_repeticiones")'),
        md("### 1.2 No respuesta de ingresos y códigos inválidos"),
        code('display(ev("02_profiling", "eph_no_respuesta_ingresos")); display(ev("02_profiling", "eph_tenencia_codigos"))'),
        md("### 1.3 Integridad y consistencia (lo que *está bien* también se documenta)"),
        code('display(ev("02_profiling", "eph_jefes_por_hogar")); display(ev("02_profiling", "eph_integridad_hogar_individuo")); display(ev("02_profiling", "eph_consistencia_itf_vs_suma_individual")); display(ev("02_profiling", "eph_formalidad_asalariados"))'),
        md("""
## 2. BCRA y salarios
Las series del BCRA vienen completas (sin huecos ni duplicados). Dos detalles:
- **La API publica la UVA con fechas futuras** (se calcula con el CER anticipado): la descarga filtra a la fecha de corte.
- **Destino del crédito (series 1113-1117):** la API rotula los saldos "en miles de pesos", pero las magnitudes corresponden a millones (se contrastó con el stock total de la serie 916). Se usan como millones y se deja la aclaración en el SQL.
"""),
        code('display(ev("02_profiling", "bcra_cobertura_series")); display(ev("02_profiling", "bcra_huecos_mensuales")); display(ev("02_profiling", "salarios_cobertura"))'),
        md("""
## 3. GCBA avisos: el dataset más sucio

### 3.1 Duplicados: en algunos años, más de la mitad de las filas
"""),
        code('ev("02_profiling", "gcba_duplicados_por_anio").set_index("anio").T'),
        md("### 3.2 Variantes de escritura de barrios (caracteres rotos, truncados, sub-barrios)"),
        code('''b = ev("02_profiling", "gcba_barrios_variantes")
b[b.barrio_tal_cual.fillna("").str.contains("NU|MONSERRAT|MONTSERRAT|MITR|AVELLANED|ESTE|OESTE|NORTE|SUR", regex=True) | b.barrio_tal_cual.isna()]'''),
        md("### 3.3 Coordenadas invertidas o inválidas y USD/m² inconsistente"),
        code('display(ev("02_profiling", "gcba_coordenadas_invalidas").set_index("anio").T); display(ev("02_profiling", "gcba_usd_m2_inconsistente").set_index("anio").T)'),
        md("""
> **Diagnóstico del USD/m² inconsistente (2016-2020):** el valor publicado se calculó sobre **m² cubiertos** y en 2001-2015 sobre **m² totales**. No es un error de carga sino un cambio de definición → se **recalcula** precio / m² total en todos los años para que la serie sea comparable.

## 4. Aplicar la limpieza
"""),
        code('run_file(con, config.ROOT / "sql" / "03_clean.sql")\nrun_file(con, config.ROOT / "sql" / "04_marts.sql")'),
        md("### 4.1 Embudo de limpieza GCBA: cuánto saca cada regla"),
        code(r'''emb = ev("03_clean", "gcba_embudo_limpieza")
fig, ax = plt.subplots(figsize=(10, 3.6))
x = emb.anio.astype(str)
descartados = emb.avisos_crudos - emb.avisos_limpios
ax.bar(x, emb.avisos_limpios, color=viz.BLUE, width=0.72, label="Avisos limpios", edgecolor=viz.SURFACE, linewidth=1)
ax.bar(x, descartados, bottom=emb.avisos_limpios, color=viz.CONTEXT_GRAY, width=0.72, label="Descartados", edgecolor=viz.SURFACE, linewidth=1)
ax.yaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.set_ylim(0, emb.avisos_crudos.max() * 1.12)
ax.legend(loc="upper left", ncols=2)
for _, r in emb[emb.pct_conservado < 70].iterrows():
    ax.annotate(fmt_pct(r.pct_conservado, 0), (str(int(r.anio)), r.avisos_crudos), xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, color=viz.INK_2)
ax.set_title("La limpieza saca sobre todo duplicados de 2016, 2017 y 2020")
viz.subtitle(ax, "Avisos por año · etiqueta = % que se conserva (solo años con menos de 70%) · reglas: tipo, precio/m², barrio, duplicados, extremos")
viz.source(fig, "GCBA, Departamentos en venta 2001-2020; elaboración propia.")
viz.save(fig, "02_gcba_embudo_limpieza")
plt.show()
emb'''),
        md("""
## 5. Validaciones posteriores a la limpieza

### 5.1 Contra el INDEC: ¿leemos bien los microdatos?
Se recalculan las cifras oficiales del informe *Evolución de la distribución del ingreso (EPH), 1T-2026* desde los microdatos. Si coinciden, la lectura, los códigos y los ponderadores están bien.
"""),
        code(r'''val = ev("03_clean", "validacion_vs_indec_1t2026")
ind = con.execute("""
    SELECT TRY_CAST(replace(IPCF, ',', '.') AS DOUBLE) AS ipcf, CAST(PONDIH AS DOUBLE) AS w
    FROM stg_eph_individual WHERE ANO4 = '2026' AND TRIMESTRE = '1' AND CAST(PONDIH AS DOUBLE) > 0
""").df().sort_values("ipcf")
w, y = ind.w.to_numpy(), ind.ipcf.to_numpy()
pop_share = np.cumsum(w) / w.sum(); inc_share = np.cumsum(w * y) / (w * y).sum()
gini = 1 - np.sum(np.diff(np.concatenate([[0], pop_share])) * (inc_share + np.concatenate([[0], inc_share[:-1]])))
pd.DataFrame({
    "Indicador": ["Población (millones)", "Mediana IPCF", "Media IPCF", "Gini IPCF"],
    "Calculado desde microdatos": [val.poblacion_millones_calc[0], val.mediana_ipcf_calc[0], val.media_ipcf_calc[0], round(gini, 3)],
    "Publicado por INDEC": [30.1, 500000, 728008, 0.442],
})'''),
        md("### 5.2 Tablas limpias y control del pool (inquilinos del pool = promedio de los 4 trimestres)"),
        code('display(ev("03_clean", "validacion_hogares_eph")); display(ev("03_clean", "validacion_pool_vs_promedio_trimestral")); display(ev("03_clean", "validacion_composicion_inquilinos")); display(ev("03_clean", "validacion_avisos_limpios")); display(ev("03_clean", "validacion_series_ultimo_dato"))'),
        md("""
### 5.3 GBA abierto por corredor
La EPH no identifica el partido del hogar. Para no usar un único precio para todo el conurbano (decisión del Checkpoint 3), cada hogar inquilino del GBA se evalúa en los **31 partidos del aglomerado**, con el precio del m² de Zonaprop de cada partido y un peso proporcional a sus **hogares inquilinos según el Censo 2022**.

- Los partidos sin precio propio (Cañuelas, Pte. Perón, San Vicente, Gral. Rodríguez y Marcos Paz) toman el promedio de su corredor ponderado por inquilinos.
- **Supuesto declarado:** la distribución de ingresos de los inquilinos es la misma en todos los partidos (la EPH no permite observarla). Por eso los corredores se leen como *escenarios de precio* sobre los mismos hogares, no como muestras independientes.
"""),
        code('display(ev("03_clean", "validacion_precios_gba")); display(ev("03_clean", "validacion_partidos_sin_match"))'),
        md(f"""
### 5.4 Contra el Censo 2022: ¿cuántos hogares y cuántos inquilinos?
Pregunta del Checkpoint 3: ¿el universo es razonable? En los 3 mercados la EPH expande **{C(c['hogares_eph_3_mercados'])} de hogares**; el Censo 2022 cuenta entre {C(c['hogares_censo_24p'])} (24 partidos) y {C(c['hogares_censo_31p'])} (31 partidos). En todo el país hay {C(c['hogares_pais_censo'])} de hogares: el {P(c['pct_propia_pais_censo'])} es propietario y el {P(c['pct_alquilada_pais_censo'])} alquila.
"""),
        code(r'''import validacion_censo
resumen = validacion_censo.main(verbose=False, con=con)
comp = pd.read_csv(EV / "validacion_censo" / "comparacion_eph_censo.csv")
display(comp.round(1))

d = comp[comp.geografia_censo.isin(["CABA", "31 partidos", "Depto. Capital"])].iloc[::-1]
etiquetas = {"CABA": "CABA", "Partidos del GBA": "Partidos del GBA\n(Censo: 31 partidos)", "Gran Córdoba": "Gran Córdoba\n(Censo: depto. Capital)"}
fig, ax = plt.subplots(figsize=(8.5, 3.0))
y = np.arange(len(d))
ax.hlines(y, d.pct_alquilada_eph, d.pct_alquilada_censo, color=viz.BASELINE, lw=2)
ax.scatter(d.pct_alquilada_eph, y, s=70, color=viz.BLUE, zorder=3, edgecolor=viz.SURFACE, linewidth=2, label="EPH (promedio 2T-25 a 1T-26)")
ax.scatter(d.pct_alquilada_censo, y, s=70, color=viz.ORANGE, zorder=3, edgecolor=viz.SURFACE, linewidth=2, label="Censo 2022")
for yi, r in zip(y, d.itertuples()):
    ax.text(max(r.pct_alquilada_eph, r.pct_alquilada_censo) + 0.8, yi, f"{fmt_decimal(r.dif_alquila_pp)} pp".replace("-", "−"), va="center", fontsize=8.5, color=viz.INK_2)
ax.set_yticks(y, [etiquetas[z] for z in d.zona])
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.xaxis.set_major_formatter(viz.EJE_PCT)
ax.set_xlim(10, 42); ax.set_ylim(-0.5, len(d) - 0.5)
ax.legend(loc="upper left")
ax.set_title("La EPH capta entre 2 y 4 puntos menos de inquilinos que el Censo")
viz.subtitle(ax, "% de hogares que alquilan · las cifras absolutas del estudio son conservadoras")
viz.source(fig, "INDEC, EPH microdatos y Censo 2022 (resultados definitivos, cuadro 6); elaboración propia.")
viz.save(fig, "02_eph_vs_censo")
plt.show()
{k: round(v, 3) for k, v in resumen.items()}'''),
        md(f"""
**Lectura:** la EPH capta algo menos de inquilinos que el Censo en los tres mercados. Si los captara igual, habría entre **{D(c['inquilinos_eph'] * c['factor_ajuste_min'] / 1e6, 2)} y {D(c['inquilinos_eph'] * c['factor_ajuste_max'] / 1e6, 2)} millones de hogares inquilinos** en lugar de {D(c['inquilinos_eph'] / 1e6, 2)} millones. Por eso las cifras absolutas se informan también como un **rango ajustado al Censo** (factor {D(c['factor_ajuste_min'], 2)} a {D(c['factor_ajuste_max'], 2)}); los porcentajes no cambian.
"""),
        code('con.execute("SELECT * FROM hogares_eph LIMIT 5").df()'),
        code("con.close()"),
    ])


# ---------------------------------------------------------------------------
# 03 · Análisis e hipótesis
# ---------------------------------------------------------------------------
def nb03():
    b, h2, h4 = K["base"], K["h2"], K["h4"]
    hit = K["contexto_mercado"]["hitos"]
    calor = {(r["zona"], r["m2"]): r["pct_elegible"] for r in K["h1"]["calor_zona"]}
    zonas = {r["zona"]: r for r in h4["por_zona"]}
    edades = {r["tramo_edad_jefe"]: r for r in h4["por_edad"]}
    perfil = {(r["tipo_hogar"], r["jefatura"]): r for r in K["h3"]["perfil"]}
    trab = {r["grupo"]: r for r in K["h7"]["por_trabajos"]}
    stress = {r["horizonte_meses"]: r for r in K["h5"]["stress_resumen"]}
    hitos_sueldo = {r["mes"]: r for r in K["h5"]["sueldo_hitos"]}
    sub = K["robustez"]["subdeclaracion"]["escenarios"]
    nr = K["robustez"]["no_respuesta"]
    tit = K["h7"]["solo_titulares"]
    ic_c = b["pasan_cuota_ic95"]
    veredicto_h1 = ("En el límite: el intervalo incluye el 20%" if ic_c[0] <= 20 <= ic_c[1]
                    else "Refutada por poco: el intervalo queda por encima del 20%" if ic_c[0] > 20 else "Confirmada")
    ult = K["h5"]["sueldo_ultimo"]
    cob = K["robustez"]["subdeclaracion"]["cobertura"]
    cob_med = sum(r["cobertura_mediana"] for r in cob) / len(cob)
    destino = {r["mes"]: r for r in K["contexto_mercado"]["destino_ultimo"]}
    d26 = destino[max(destino)]
    total_d26 = d26["compra_usada"] + d26["compra_nueva"] + d26["construccion"] + d26["refaccion"] + d26["otros"]
    pct_compra = 100 * (d26["compra_usada"] + d26["compra_nueva"]) / total_d26

    return notebook([
        md(f"""
# 03 · Análisis e hipótesis: ¿quién puede pagar hoy un hipotecario UVA?

**Decisión que apoya:** a qué hogares apuntar, con qué producto y con qué política de riesgo (`reports/00_encuadre.md`).

1. Contexto de mercado: crédito, destino y cuánta vivienda compra un sueldo
2. El embudo de elegibilidad
3. H1 · ¿Cuántos pueden pagar? Mapa de calor por superficie
4. H2 · ¿Frena la cuota o el anticipo?
5. H3 · Composición del hogar (descriptivo)
6. H4 · Diferencias por zona y edad
7. H5 · Riesgo: la cuota frente a los sueldos
8. Recuadro H7 · Trabajos en el hogar (posible punto de fuga)
9. Robustez: Censo, subdeclaración y no respuesta
10. Tablero de hipótesis

> Las funciones de cálculo viven en `src/affordability.py` y `src/analysis.py`; son las mismas que alimentan el dashboard, los documentos y la presentación.
"""),
        code(BASE_ANALISIS),

        md("## 1. Contexto de mercado\n### 1.1 El crédito volvió, pero el stock real es la mitad del pico de 2018"),
        code(r'''mc = con.execute("SELECT * FROM mart_mercado_credito ORDER BY mes").df()
hitos = K["contexto_mercado"]["hitos"]
fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.9))
bajo = mc[mc.periodo_bajo_volumen]
for ax in axes:
    ax.axvspan(bajo.mes.min(), bajo.mes.max(), color=viz.GRID, alpha=0.6, lw=0)
ax = axes[0]
ax.plot(mc.mes, mc.stock_real_billones_ago26, color=viz.BLUE)
ax.set_title("Stock real de hipotecarios a personas")
viz.subtitle(ax, "Billones de pesos de agosto de 2026")
pico = mc.loc[mc.stock_real_billones_ago26.idxmax()]; ult = mc.dropna(subset=["stock_real_billones_ago26"]).iloc[-1]
ax.annotate(f"Pico may-18: {fmt_decimal(pico.stock_real_billones_ago26)}", (pico.mes, pico.stock_real_billones_ago26), xytext=(14, -10), textcoords="offset points", fontsize=8.5, color=viz.INK_2, va="top")
ax.annotate(f"{fmt_mes(ult.mes).capitalize()}: {fmt_decimal(ult.stock_real_billones_ago26)} ({fmt_pct(hitos['pct_del_pico'], 0)} del pico)", (ult.mes, ult.stock_real_billones_ago26), xytext=(-165, 18), textcoords="offset points", fontsize=8.5, color=viz.INK_2, arrowprops=dict(arrowstyle="-", color=viz.MUTED, lw=0.8))
ax.yaxis.set_major_formatter(viz.EJE_DECIMAL)
ax = axes[1]
ax.plot(mc.mes, mc.tasa_hip_uva, color=viz.BLUE)
ax.set_title("Tasa promedio de hipotecarios UVA (TNA %)")
viz.subtitle(ax, "Zona gris: 2022-24, casi sin otorgamientos (tasa poco representativa)")
t = mc.dropna(subset=["tasa_hip_uva"]).iloc[-1]
ax.annotate(fmt_pct(t.tasa_hip_uva, 2), (t.mes, t.tasa_hip_uva), xytext=(4, 4), textcoords="offset points", fontsize=8.5, color=viz.INK_2)
viz.source(fig, "BCRA, API de Estadísticas (series 916, 1240, 27); elaboración propia.")
fig.tight_layout()
viz.save(fig, "03_mercado_credito")
plt.show()
pd.DataFrame(K["contexto_mercado"]["correlaciones"]).round(2)'''),
        md(f"""
**Lectura (contexto, ex H6):** el stock real llegó a {D(hit['stock_pico_billones'])} billones en {hit['mes_pico']}, cayó a {D(hit['stock_minimo_billones'], 2)} en {hit['mes_minimo']} y hoy está en {D(hit['stock_ultimo_billones'])} ({P(hit['pct_del_pico'], 0)} del pico). La relación entre tasa y crecimiento del stock es **débil y negativa**; con pocos ciclos y muchos factores a la vez (inflación, cepo, programas oficiales) se usa como **contexto, no como hipótesis causal**.

### 1.2 ¿Para qué se usa el crédito hipotecario?
"""),
        code(r'''dest = con.execute("SELECT * FROM mart_destino_credito ORDER BY mes").df()
series = [("compra_usada_billones_ago26", "Compra de vivienda usada"), ("compra_nueva_billones_ago26", "Compra de vivienda nueva"),
          ("construccion_billones_ago26", "Construcción"), ("refaccion_billones_ago26", "Refacción"), ("otros_billones_ago26", "Otros destinos")]
fig, ax = plt.subplots(figsize=(10.5, 4.0))
ax.stackplot(dest.mes, *[dest[c] for c, _ in series], labels=[l for _, l in series], colors=viz.SERIES[:5], edgecolor=viz.SURFACE, linewidth=0.8)
ax.yaxis.set_major_formatter(viz.EJE_DECIMAL)
ax.legend(loc="upper right", ncols=1)
u = dest.iloc[-1]
total = sum(u[c] for c, _ in series)
compra = u.compra_usada_billones_ago26 + u.compra_nueva_billones_ago26
ax.set_title(f"{round(10 * compra / total)} de cada 10 pesos del crédito hipotecario financian la compra de una vivienda")
viz.subtitle(ax, f"Saldo por destino · billones de pesos de agosto de 2026 · último dato {fmt_mes(u.mes)}")
viz.source(fig, "BCRA, API de Estadísticas (series 1113 a 1117), deflactado por IPC; elaboración propia.")
viz.save(fig, "03_destino_credito")
plt.show()
pd.DataFrame(K["contexto_mercado"]["destino_ultimo"])'''),
        md(f"""
**Lectura:** en {d26['mes']} el {P(pct_compra, 0)} del saldo financia compra de vivienda (nueva o usada). Construcción y refacción son marginales: el producto relevante para inquilinos es **compra**.

### 1.3 ¿Cuántos m² de CABA compra un sueldo formal?
"""),
        code(r'''ms = con.execute("SELECT * FROM mart_m2_por_salario ORDER BY anio").df()
hist = ms[ms.anio <= 2020]; hoy = ms[ms.anio == 2026].iloc[0]
fig, ax = plt.subplots(figsize=(10.5, 3.9))
for a, b_, txt in [(2000.5, 2001.5, "convertibilidad"), (2011.5, 2015.9, "cepo"), (2019.6, 2020.5, "cepo")]:
    ax.axvspan(a, b_, color=viz.GRID, alpha=0.6, lw=0)
    ax.text((a + b_) / 2, 0.04, txt, ha="center", fontsize=8, color=viz.MUTED, rotation=90 if b_ - a < 1.5 else 0, va="bottom")
prom = hist[(hist.anio >= 2002) & (hist.anio <= 2017)].m2_por_salario.mean()
ax.axhline(prom, color=viz.BASELINE, lw=1)
ax.text(2021, prom + 0.015, f"promedio 2002-2017: {fmt_decimal(prom, 2)}", fontsize=8, color=viz.MUTED, va="bottom")
ax.yaxis.set_major_formatter(viz.EJE_DECIMAL)
ax.plot(hist.anio, hist.m2_por_salario, color=viz.BLUE, marker="o", ms=4)
ax.plot([hoy.anio], [hoy.m2_por_salario], marker="o", ms=8, mfc=viz.SURFACE, mec=viz.ORANGE, mew=2, ls="none")
ax.annotate(f"2026: {fmt_decimal(hoy.m2_por_salario, 2)} m²\n(Zonaprop, otra metodología)", (hoy.anio, hoy.m2_por_salario), xytext=(-40, 26), textcoords="offset points", fontsize=8.5, color=viz.INK_2, ha="center")
for yr in (2001, 2015, 2020):
    r = ms[ms.anio == yr].iloc[0]
    ax.annotate(fmt_decimal(r.m2_por_salario, 2), (yr, r.m2_por_salario), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8.5, color=viz.INK_2)
ax.set_xlim(2000, 2027); ax.set_ylim(0, 1.12)
ax.set_title("Un sueldo formal compra medio m² en CABA: salió del piso de 2019-20 y está cerca del promedio histórico")
viz.subtitle(ax, "m² de departamento por sueldo formal promedio (RIPTE en USD) · con convertibilidad o cepo el dólar oficial sobreestima el poder de compra")
viz.source(fig, "GCBA avisos 2001-2020 (mediana), Zonaprop Index jul-26, RIPTE, BCRA; elaboración propia.")
viz.save(fig, "03_m2_por_salario")
plt.show()
ms[["anio", "fuente_precio", "usd_m2_mediana", "ripte_usd", "m2_por_salario", "anios_de_salario_60m2"]].round(2)'''),

        md(f"""
## 2. El embudo de elegibilidad

**Escenario base** (Checkpoints 1 y 2): UVA + 7,5% · 20 años · 75% financiado · cuota hasta 25% del ingreso · anticipo + gastos hasta 12 ingresos mensuales · ingreso demostrable (jefe/a o cónyuge asalariado con aportes) · edad al terminar hasta 85 años.

**Qué es un hogar inquilino:** un hogar (personas que comparten la vivienda y los gastos de comida) que declara alquilar la vivienda donde vive (EPH, pregunta II7 = 3). **Base:** los {C(K['universo']['inquilinos'])} de hogares inquilinos de los 3 mercados; el embudo se calcula sobre los que declararon su ingreso, con el peso `PONDIH` que representa también a los que no lo hicieron.
"""),
        code(r'''emb = embudo(ev)
fig, ax = plt.subplots(figsize=(10, 3.8))
colores = ["#86b6ef", "#5598e7", "#3987e5", "#256abf", "#184f95"]
y = np.arange(len(emb))[::-1]
ax.barh(y, emb.hogares, color=colores, height=0.62)
ax.set_yticks(y, emb.etapa)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.xaxis.set_major_formatter(viz.EJE_CANTIDAD)
for yi, r in zip(y, emb.itertuples()):
    ax.text(r.hogares + emb.hogares.max() * 0.01, yi, f"{fmt_cantidad(r.hogares)} · {fmt_pct(r.pct_del_total)}", va="center", fontsize=9, color=viz.INK_2)
ax.set_xlim(0, emb.hogares.max() * 1.25)
pct_final = emb.pct_del_total.iloc[-1]
ax.set_title(f"Solo 1 de cada {round(100 / pct_final)} hogares inquilinos podría tomar hoy un hipotecario UVA")
viz.subtitle(ax, "Hogares inquilinos que superan cada filtro (acumulado) · CABA, Partidos del GBA y Gran Córdoba · escenario base")
viz.source(fig, "INDEC EPH 2T-25 a 1T-26, BCRA, Zonaprop Index; elaboración propia.")
viz.save(fig, "03_embudo_elegibilidad")
plt.show()
display(emb)
embudo(ev, "zona").pivot(index="etapa", columns="zona", values="pct_del_total").loc[ETAPAS].round(1)'''),

        md(f"""
## 3. H1 · ¿Menos del 20% de los inquilinos puede pagar la cuota?
"""),
        code("A.h1_intervalos(h, m, base)"),
        md(f"""
**Lectura H1:** el {P(b['pasan_cuota_pct'])} de los hogares inquilinos puede pagar la cuota (IC 95% {D(ic_c[0])}–{D(ic_c[1])}) y el **{P(b['elegibles_pct'])} pasa el embudo completo** (IC {D(b['elegibles_ic95'][0])}–{D(b['elegibles_ic95'][1])}), es decir **{H(b['elegibles_hogares'])}** ({C(b['elegibles_rango_censo'][0])} a {C(b['elegibles_rango_censo'][1])} ajustado al Censo). Veredicto: **{veredicto_h1.lower()}**.

> Los intervalos son aproximados: la base usuaria de la EPH no publica conglomerados ni estratos del diseño muestral, así que el bootstrap por hogar probablemente los subestima un poco.

### 3.1 Mapa de calor: ¿y si cambia la superficie?
**Decisión (Checkpoint 3):** no fijar una regla de m² por tamaño de hogar. En lugar de eso, se muestra qué pasa con la elegibilidad si todos buscaran la misma superficie, de 30 a 90 m². La regla de referencia (45 m² hasta 2 personas, 60 m² para 3-4, 75 m² para 5 o más) queda marcada en el eje.
"""),
        code(r'''calor_z, calor_i = A.h1_mapa_calor(h, m, base)

def mapa_calor(tabla, filas, titulo, bajada, archivo, etiqueta_filas):
    g = tabla.pivot(index=etiqueta_filas, columns="m2", values="pct_elegible").loc[filas]
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(filas) + 1.6))
    ax.imshow(g.values, cmap=RAMPA, aspect="auto", vmin=0, vmax=40)
    ax.set_xticks(range(g.shape[1]), [f"{c}" for c in g.columns])
    ax.set_yticks(range(g.shape[0]), g.index)
    ax.grid(False)
    for s in ax.spines.values(): s.set_visible(False)
    for i in range(g.shape[0]):
        for j in range(g.shape[1]):
            v = g.values[i, j]
            ax.text(j, i, fmt_decimal(v, 0), ha="center", va="center", fontsize=8.5, color=tinta_sobre(min(v, 40), 0, 40))
    for c in (45, 60, 75):
        ax.get_xticklabels()[list(g.columns).index(c)].set_fontweight("bold")
    if "Total" in g.index:
        ax.axhline(len(g.index) - 1.5, color=viz.SURFACE, lw=4)
    ax.set_xlabel("m² de la vivienda (en negrita, la referencia por tamaño de hogar: 45, 60 y 75)")
    ax.set_title(titulo)
    viz.subtitle(ax, bajada)
    viz.source(fig, "INDEC EPH, Zonaprop Index, BCRA; elaboración propia.")
    viz.save(fig, archivo)
    plt.show()
    return g

tot = calor_z[calor_z.zona == "Total"].set_index("m2").pct_elegible
gz = mapa_calor(calor_z, ["CABA", "GBA Norte", "GBA Sur", "GBA Oeste", "Gran Córdoba", "Total"],
                f"Con 30 m² calificaría 1 de cada {round(100 / tot[30])} hogares inquilinos; con 60 m², 1 de cada {round(100 / tot[60])}",
                "% de hogares inquilinos elegibles si buscaran una vivienda de esa superficie · escenario base",
                "03_calor_m2_zona", "zona")
gi = mapa_calor(calor_i, ["1", "2", "3", "4", "5 o más"],
                "Los hogares de una sola persona son los que menos califican, en cualquier superficie",
                "% de hogares inquilinos elegibles según integrantes y superficie buscada · escenario base",
                "03_calor_m2_integrantes", "integrantes")
display(gz.round(1)); display(gi.round(1))'''),
        md(f"""
**Lectura:** con 45 m² (un 2 ambientes chico) calificaría el {P(calor[('Total', 45)])} de los inquilinos; con 60 m², el {P(calor[('Total', 60)])}; con 75 m², el {P(calor[('Total', 75)])}. En **CABA** la proporción pasa de {P(calor[('CABA', 45)])} a {P(calor[('CABA', 75)])} entre 45 y 75 m²; en **GBA Oeste**, de {P(calor[('GBA Oeste', 45)])} a {P(calor[('GBA Oeste', 75)])}. Los **hogares de una persona** tienen la elegibilidad más baja en cualquier superficie: dependen de un solo ingreso.

## 4. H2 · ¿La barrera es el anticipo o la cuota?
Con los supuestos del escenario, **cuota y anticipo dependen del mismo número**: cuánto cuesta la vivienda medido en ingresos mensuales del hogar.
"""),
        code(r'''b = A.h2_barreras(ev, base)
ev["precio_en_ingresos"] = ev.precio_ars / ev.ingreso
mediana = A.wquant(ev.precio_en_ingresos, ev.peso, 0.5)
fig, ax = plt.subplots(figsize=(10, 3.8))
x = ev.precio_en_ingresos.clip(upper=200)
ax.hist(x, bins=np.arange(0, 205, 5), weights=ev.peso, color=viz.BLUE, edgecolor=viz.SURFACE, linewidth=1)
ax.axvline(b["precio_max_ingresos_por_anticipo"], color=viz.INK, lw=1.2)
ax.axvline(b["precio_max_ingresos_por_cuota"], color=viz.INK_2, lw=1.2)
ymax = ax.get_ylim()[1]
ax.text(b["precio_max_ingresos_por_anticipo"] - 1.5, ymax * 0.93, f"Tope por anticipo: {fmt_decimal(b['precio_max_ingresos_por_anticipo'])}", ha="right", fontsize=8.5, color=viz.INK)
ax.text(b["precio_max_ingresos_por_cuota"] + 1.5, ymax * 0.80, f"Tope por cuota: {fmt_decimal(b['precio_max_ingresos_por_cuota'])}", ha="left", fontsize=8.5, color=viz.INK_2)
ax.axvline(mediana, color=viz.MUTED, lw=1)
ax.text(mediana + 1.5, ymax * 0.62, f"Mediana de los inquilinos: {fmt_decimal(mediana, 0)} ingresos", ha="left", fontsize=8.5, color=viz.INK_2)
ax.yaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.set_xlabel("Precio de la vivienda de referencia, en ingresos mensuales del hogar (200 = 200 o más)")
ax.set_title("La vivienda típica cuesta casi el doble de lo que un hogar inquilino puede financiar")
viz.subtitle(ax, "Hogares inquilinos según precio/ingreso · a la izquierda de las líneas califican")
viz.source(fig, "INDEC EPH, Zonaprop Index, BCRA; elaboración propia.")
viz.save(fig, "03_precio_en_ingresos")
plt.show()
pd.Series(b).to_frame("valor")'''),
        md(f"""
**Lectura H2:** en sentido estricto, **el anticipo es la restricción más exigente**: una vivienda puede costar hasta {D(h2['precio_max_ingresos_por_anticipo'])} ingresos por el anticipo y {D(h2['precio_max_ingresos_por_cuota'])} por la cuota, y ningún hogar pasa el anticipo sin pasar la cuota. Pero el **{P(h2['pct_fallan_ambos'], 0)} no alcanza ninguna de las dos**: la vivienda de referencia cuesta una mediana de {D(h2['mediana_precio_en_ingresos'], 0)} ingresos mensuales.

**Implicancia de producto:** bajar la tasa, alargar el plazo o subir el tope de cuota **no suma hogares por sí solos** (mueven la línea de la cuota, que no es la que frena). El % financiado de equilibrio es {P(100 * h2['ltv_equilibrio'], 0)}: la palanca real es **financiar más junto con más plazo** (notebook 04).

## 5. H3 · ¿Cómo son los hogares inquilinos y quiénes califican?
**Decisión (Checkpoint 3):** mirada **descriptiva y neutral**. Se describe la composición del hogar y, dentro de ella, quién figura como jefe o jefa (la persona que el propio hogar reconoce como tal en la encuesta). No se hacen afirmaciones causales.
"""),
        code(r'''h3 = A.h3_perfil_hogares(h, m, base)
orden = ["Pareja sin hijos", "Pareja con hijos", "Extendido o compuesto", "Unipersonal", "Monoparental"]
t = h3[h3.agrupacion == "tipo_hogar"].set_index("tipo_hogar").loc[orden]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.6), sharey=True, gridspec_kw={"width_ratios": [1, 1.25]})
y = np.arange(len(t))[::-1]
a1.barh(y, t.pct_de_inquilinos, color=viz.BLUE, height=0.55)
for yi, r in zip(y, t.itertuples()):
    a1.text(r.pct_de_inquilinos + 0.8, yi, fmt_pct(r.pct_de_inquilinos, 0), va="center", fontsize=8.5, color=viz.INK_2)
a1.set_yticks(y, t.index); a1.set_xlim(0, t.pct_de_inquilinos.max() * 1.25)
a1.grid(axis="y", visible=False); a1.grid(axis="x", visible=True); a1.xaxis.set_major_formatter(viz.EJE_PCT)
a1.set_title("¿Cuántos son?", fontsize=10.5); viz.subtitle(a1, "% de los hogares inquilinos")
a2.errorbar(t.pct_elegible, y, xerr=[t.pct_elegible - t.ic95_inf, t.ic95_sup - t.pct_elegible], fmt="none", ecolor=viz.BASELINE, elinewidth=2)
a2.scatter(t.pct_elegible, y, s=60, color=viz.BLUE, zorder=3, edgecolor=viz.SURFACE, linewidth=1.5)
for yi, r in zip(y, t.itertuples()):
    a2.text(r.ic95_sup + 0.8, yi, f"{fmt_pct(r.pct_elegible)} · ingreso por persona {fmt_monto(r.ingreso_por_persona_mediano)}", va="center", fontsize=8.5, color=viz.INK_2)
a2.set_xlim(0, t.ic95_sup.max() + 30); a2.grid(axis="y", visible=False); a2.grid(axis="x", visible=True); a2.xaxis.set_major_formatter(viz.EJE_PCT)
a2.set_title("¿Cuántos califican?", fontsize=10.5); viz.subtitle(a2, "% elegible · punto = estimación · línea = IC 95%")
viz.titulo_figura(fig, "Las parejas sin hijos califican varias veces más que los hogares con un solo adulto")
viz.source(fig, "INDEC EPH (CH03, CH04); elaboración propia. Ingreso por persona: mediana, pesos de agosto de 2026.")
viz.save(fig, "03_perfil_hogares")
plt.show()
h3[["agrupacion", "tipo_hogar", "jefatura", "hogares", "pct_de_inquilinos", "muestra_hogares", "ingreso_mediano", "ingreso_por_persona_mediano",
    "perceptores_promedio", "pct_ingreso_demostrable", "pct_elegible", "ic95_inf", "ic95_sup", "muestra_chica"]].round(1)'''),
        md(f"""
**Lectura H3 (descriptiva):**
- Las **parejas con hijos** son el grupo más numeroso ({P(perfil[('Pareja con hijos', 'Todas')]['pct_de_inquilinos'], 0)} de los inquilinos) y califica el {P(perfil[('Pareja con hijos', 'Todas')]['pct_elegible'])}.
- Las **parejas sin hijos** tienen la mayor elegibilidad ({P(perfil[('Pareja sin hijos', 'Todas')]['pct_elegible'])}): suelen tener dos ingresos y el ingreso por persona más alto.
- Los hogares con **un solo adulto** (unipersonales {P(perfil[('Unipersonal', 'Todas')]['pct_elegible'])}, monoparentales {P(perfil[('Monoparental', 'Todas')]['pct_elegible'])}) dependen de un ingreso y quedan mayormente afuera.
- **Jefatura:** en las parejas, la elegibilidad es similar según quién figura como jefe/a ({P(perfil[('Pareja con hijos', 'Mujer')]['pct_elegible'])} y {P(perfil[('Pareja con hijos', 'Varón')]['pct_elegible'])} en parejas con hijos). Las diferencias aparecen en los hogares de un solo adulto, donde el ingreso por persona es más bajo cuando encabeza una mujer. Hay celdas con **muestra chica** (marcadas en la tabla): se muestran como referencia, no como conclusión.

## 6. H4 · ¿La elegibilidad cambia según la zona y la edad?
"""),
        code(r'''t_zona, test_zona = A.h4_por_grupo(h, m, "zona", base)
t_edad, test_edad = A.h4_por_grupo(h, m, "tramo_edad_jefe", base)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.4))
for ax, t, col, test, titulo in [(a1, t_zona, "zona", test_zona, "Por zona"), (a2, t_edad.sort_values("tramo_edad_jefe", ascending=False), "tramo_edad_jefe", test_edad, "Por edad de jefe/a")]:
    d = t.sort_values("pct_elegible") if col == "zona" else t
    y = np.arange(len(d))
    ax.errorbar(d.pct_elegible, y, xerr=[d.pct_elegible - d.ic95_inf, d.ic95_sup - d.pct_elegible], fmt="none", ecolor=viz.BASELINE, elinewidth=2)
    ax.scatter(d.pct_elegible, y, s=60, color=viz.BLUE, zorder=3, edgecolor=viz.SURFACE, linewidth=1.5)
    for yi, r in zip(y, d.itertuples()):
        ax.text(r.ic95_sup + 0.6, yi, f"{fmt_pct(r.pct_elegible)} · {fmt_cantidad(r.hogares_elegibles)}", va="center", fontsize=8.5, color=viz.INK_2)
    ax.set_yticks(y, d[col]); ax.set_xlim(0, 36)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True); ax.xaxis.set_major_formatter(viz.EJE_PCT)
    ax.set_title(titulo, fontsize=10.5)
    viz.subtitle(ax, f"% elegible · hogares elegibles · p = {fmt_decimal(test['p_valor'], 2)}")
viz.titulo_figura(fig, "La elegibilidad sigue al precio del m² y a la edad: la edad es concluyente, la zona todavía no")
viz.source(fig, "INDEC EPH, Zonaprop Index, BCRA; elaboración propia. Corredores del GBA: mismos hogares evaluados con los precios de cada corredor.")
viz.save(fig, "03_elegibles_por_zona_edad")
plt.show()
display(t_zona); print(test_zona); display(t_edad); print(test_edad)'''),
        md(f"""
**Lectura H4:**
- **Zona:** la proporción de elegibles va de {P(zonas['GBA Norte']['pct_elegible'])} en GBA Norte (m² más caro del conurbano) a {P(zonas['GBA Oeste']['pct_elegible'])} en GBA Oeste; Gran Córdoba tiene {P(zonas['Gran Córdoba']['pct_elegible'])} y CABA {P(zonas['CABA']['pct_elegible'])}. Entre mercados la diferencia **no es estadísticamente concluyente** (p = {D(h4['test_zona']['p_valor'], 2)}, ajustado por efecto de diseño). En volumen, **CABA aporta la mayor cantidad de elegibles** ({C(zonas['CABA']['hogares_elegibles'])}).
- **Edad:** diferencia significativa (p = {D(h4['test_edad']['p_valor'], 2)}). Con 20 años de plazo, desde los 66 años no se cumple la edad máxima; los grupos de 30-39 y 50-64 años son los de mayor elegibilidad.
- **Veredicto:** parcialmente confirmada (edad sí; zona, dirección esperada pero no concluyente).

## 7. H5 · Riesgo: ¿qué pasa si la UVA le gana a los sueldos?
**Cómo se lee el stress test, paso a paso:**
1. Un hogar toma el crédito con una cuota igual al 25% de su ingreso.
2. La cuota se mueve con la UVA (inflación) y el ingreso con el índice de salarios registrados.
3. Si los precios suben más rápido que los sueldos, la cuota pasa a pesar más del 25%.
"""),
        code(r'''st = con.execute("SELECT * FROM mart_stress_uva_salarios").df()
res = pd.DataFrame(K["h5"]["stress_resumen"])
fig, ax = plt.subplots(figsize=(10, 3.9))
for inicio, color, etiqueta in [("2018-05-01", viz.ORANGE, "Crédito tomado en may-2018"), ("2023-09-01", viz.BLUE, "Crédito tomado en sep-2023")]:
    s = st[st.inicio == pd.Timestamp(inicio)].sort_values("meses_transcurridos")
    ax.plot(s.meses_transcurridos, 100 * s.cuota_ingreso, color=color, label=etiqueta)
    ax.annotate(fmt_pct(100 * s.cuota_ingreso.iloc[-1]), (s.meses_transcurridos.iloc[-1], 100 * s.cuota_ingreso.iloc[-1]), xytext=(5, 0), textcoords="offset points", va="center", fontsize=9, color=viz.INK_2)
for nivel, txt, x, dy, va in [(25, "cuota al otorgar: 25%", 20, -0.3, "top"), (30, "30% del ingreso", 12, 0.25, "bottom")]:
    ax.axhline(nivel, color=viz.BASELINE, lw=1)
    ax.text(x, nivel + dy, txt, fontsize=8, color=viz.MUTED, ha="left", va=va)
ax.set_xlim(0, 39); ax.set_ylim(22, 36)
ax.yaxis.set_major_formatter(viz.EJE_PCT)
ax.set_xlabel("Meses desde que se tomó el crédito")
ax.legend(loc="upper left")
ax.set_title("Si la UVA le gana a los sueldos, la cuota pasa del 25% a un tercio del ingreso")
viz.subtitle(ax, "Cuota/ingreso de un deudor que empezó en 25%, con salarios registrados (INDEC)")
viz.source(fig, "BCRA (UVA), INDEC Índice de salarios, sector registrado; elaboración propia.")
viz.save(fig, "03_stress_uva_salarios")
plt.show()
res'''),
        md(f"""
**Lectura:** un crédito tomado en **sep-2023** llegó a {P(stress[24]['peor_cuota_ingreso_pct'])} del ingreso a los 24 meses. El {P(stress[24]['pct_ventanas_sobre_30'], 0)} de todas las ventanas de 24 meses desde 2016 supera el 30%. **Implicancia:** otorgar con tope de cuota 30% (en vez de 25%) dejaría a esos deudores cerca del 40% en un episodio así → mantener el **25%** y evaluar protecciones (por ejemplo, un tope de cuota atado a salarios).

### 7.1 El sueldo en tres lentes
**Pedido del Checkpoint 3:** mostrar cómo evolucionaron los sueldos en el mismo período frente a la inflación y en dólares. Se usa la **mediana de la remuneración bruta de asalariados registrados del sector privado (SIPA)**; se excluyen junio y diciembre porque incluyen aguinaldo.
"""),
        code(r'''tl = con.execute("SELECT * FROM mart_sueldo_tres_lentes ORDER BY mes").df()
fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.2), sharex=True)
ax = axes[0]
for col, color, nombre in [("indice_ipc", viz.ORANGE, "Precios (IPC)"), ("indice_uva", viz.AQUA, "UVA"), ("indice_sueldo", viz.BLUE, "Sueldo")]:
    ax.plot(tl.mes, tl[col], color=color, label=nombre)
u = tl.iloc[-1]
ax.annotate(f"Precios ×{fmt_decimal(u.indice_ipc / 100, 0)} · UVA ×{fmt_decimal(u.indice_uva / 100, 0)}", (u.mes, u.indice_uva), xytext=(6, 8), textcoords="offset points", fontsize=8.5, color=viz.INK_2, va="bottom")
ax.annotate(f"Sueldo ×{fmt_decimal(u.indice_sueldo / 100, 0)}", (u.mes, u.indice_sueldo), xytext=(6, -8), textcoords="offset points", fontsize=8.5, color=viz.INK_2, va="top")
ax.set_yscale("log")
ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: fmt_cantidad(v)))
ax.yaxis.set_minor_formatter(mtick.NullFormatter())
ax.legend(loc="upper left")
ax.set_title(f"1 · En pesos: el sueldo se multiplicó por {fmt_decimal(tl.indice_sueldo.iloc[-1] / 100, 0)}; los precios, por {fmt_decimal(tl.indice_ipc.iloc[-1] / 100, 0)}", fontsize=10.5)
viz.subtitle(ax, "Índice abril 2016 = 100 · escala logarítmica")
ax = axes[1]
ax.plot(tl.mes, tl.sueldo_usd_bna, color=viz.BLUE)
for mes in ["2017-11-01", "2019-11-01"]:
    r = tl[tl.mes == pd.Timestamp(mes)].iloc[0]
    ax.annotate(f"{fmt_mes(r.mes)}: {fmt_monto(r.sueldo_usd_bna, 'USD', exacto=True)}", (r.mes, r.sueldo_usd_bna), xytext=(0, 9 if mes.startswith("2017") else -14), textcoords="offset points", ha="center", fontsize=8.5, color=viz.INK_2)
r = tl.iloc[-1]
ax.annotate(f"{fmt_mes(r.mes)}: {fmt_monto(r.sueldo_usd_bna, 'USD', exacto=True)}", (r.mes, r.sueldo_usd_bna), xytext=(-10, 10), textcoords="offset points", ha="right", fontsize=8.5, color=viz.INK_2)
ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: fmt_monto(v, "USD", exacto=True)))
ax.set_ylim(0, tl.sueldo_usd_bna.max() * 1.2)
ax.set_title("2 · En dólares: volvió cerca del nivel de 2017", fontsize=10.5)
viz.subtitle(ax, "Sueldo mediano en dólares al tipo de cambio Banco Nación vendedor (promedio mensual)")
ax = axes[2]
ax.plot(tl.mes, tl.sueldo_real_pesos_ago26, color=viz.BLUE)
for idx in [tl.sueldo_real_pesos_ago26.idxmax(), tl.index[-1]]:
    r = tl.loc[idx]
    ax.annotate(f"{fmt_mes(r.mes)}: {fmt_monto(r.sueldo_real_pesos_ago26)}", (r.mes, r.sueldo_real_pesos_ago26), xytext=(0, 9), textcoords="offset points", ha="center" if idx != tl.index[-1] else "right", fontsize=8.5, color=viz.INK_2)
ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: fmt_monto(v)))
ax.set_ylim(0, tl.sueldo_real_pesos_ago26.max() * 1.2)
ax.set_title("3 · En poder de compra: todavía está por debajo de 2017", fontsize=10.5)
viz.subtitle(ax, "Sueldo mediano en pesos de agosto de 2026 (ajustado por IPC)")
viz.source(fig, "SIPA (remuneración bruta mediana, sector privado registrado), INDEC IPC, BCRA UVA, Banco Nación; elaboración propia.")
fig.tight_layout()
viz.titulo_figura(fig, "El sueldo registrado recuperó dólares, pero no poder de compra")
viz.save(fig, "03_sueldo_tres_lentes")
plt.show()
pd.DataFrame(K["h5"]["sueldo_hitos"])'''),
        md(f"""
**Lectura:** el sueldo mediano registrado ({M(ult['bruto'])} brutos en {ult['mes']}) equivale a {M(ult['usd_bna'], 'USD', exacto=True)} al dólar Banco Nación, cerca de los {M(hitos_sueldo['2017-11']['sueldo_usd_bna'], 'USD', exacto=True)} de nov-2017 y lejos del piso de {M(hitos_sueldo['2019-11']['sueldo_usd_bna'], 'USD', exacto=True)} de nov-2019. En poder de compra, en cambio, vale {M(ult['real_ago26'])} de agosto de 2026, contra {M(hitos_sueldo['2017-11']['sueldo_real_ago26'])} en 2017. Para quien compra en dólares y paga en UVA, las dos lentes importan: el dólar define el precio y la UVA la cuota.

> Los ingresos de **independientes** (monotributistas y autónomos) no tienen un índice oficial comparable; su análisis está en el notebook 05, separado para no alterar la base de asalariados.

## 8. Recuadro H7 · Posible punto de fuga: trabajos en el hogar
*Detalle ampliado a pedido del Checkpoint 3. Se muestra como aclaración, no como hallazgo central.* Se cuentan los **trabajos de todas las personas del hogar** (EPH `PP03C`/`PP03D`): una persona con 2 empleos cuenta 2.
"""),
        code(r'''fu = A.acceso_por_fuentes(h, m, base)
det = fu[fu.variable == "detalle_trabajo"].set_index("grupo").loc[["Sin trabajo en el hogar", "1 persona con 1 trabajo", "1 persona con 2 o más trabajos", "2 o más personas trabajando"]]
fig, ax = plt.subplots(figsize=(10, 3.4))
y = np.arange(len(det))[::-1]
ax.errorbar(det.pct_elegible, y, xerr=[det.pct_elegible - det.ic95_inf, det.ic95_sup - det.pct_elegible], fmt="none", ecolor=viz.BASELINE, elinewidth=2)
ax.scatter(det.pct_elegible, y, s=60, color=viz.BLUE, zorder=3, edgecolor=viz.SURFACE, linewidth=1.5)
for yi, (g, r) in zip(y, det.iterrows()):
    ax.text(max(r.ic95_sup, r.pct_elegible) + 0.6, yi, f"{fmt_pct(r.pct_elegible)} elegible · {fmt_pct(r.pct_de_inquilinos, 0)} de los inquilinos · {fmt_pct(r.pct_con_ingreso_demostrable, 0)} con ingreso demostrable", va="center", fontsize=8.5, color=viz.INK_2)
ax.set_yticks(y, det.index)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.xaxis.set_major_formatter(viz.EJE_PCT)
ax.set_xlim(-0.5, det.ic95_sup.max() + 30)
ax.set_title("Lo que hace la diferencia es que trabajen dos personas, no tener dos empleos")
viz.subtitle(ax, "% de hogares inquilinos elegibles según los trabajos del hogar · punto = estimación · línea = IC 95%")
viz.source(fig, "INDEC EPH (PP03C, PP03D); elaboración propia.")
viz.save(fig, "03_acceso_por_trabajos")
plt.show()
display(fu.round(1)); A.escenario_solo_titulares(h, m, base)'''),
        md(f"""
> **Recuadro · posible punto de fuga.** Donde trabajan **dos o más personas**, califica el {P(trab['2 o más personas trabajando']['pct_elegible'])}; con **una persona y un trabajo**, el {P(trab['1 persona con 1 trabajo']['pct_elegible'])}. Una persona con **dos empleos** pasa más seguido los filtros de cuota y anticipo ({P(trab['1 persona con 2 o más trabajos']['pct_pasan_cuota_y_anticipo'])}), pero solo el {P(trab['1 persona con 2 o más trabajos']['pct_con_ingreso_demostrable'], 0)} tiene ingreso demostrable: el segundo empleo suele ser informal. Si el banco computa solo el ingreso de **jefe/a y cónyuge**, los elegibles bajan {P(abs(tit['diferencia_pct']), 0)}. El punto de fuga: hogares que **pueden pagar con ingresos que el banco no ve**.

## 9. Robustez: ¿la conclusión depende de los supuestos?
Tres controles pedidos en el Checkpoint 3:
1. **Censo 2022:** la EPH capta menos inquilinos → rango ajustado de hogares elegibles (notebook 02).
2. **Subdeclaración de ingresos:** la EPH capta en promedio el {P(100 * cob_med, 0)} del sueldo mediano formal que registra el SIPA (neto de aportes). Se corrigen **solo los sueldos formales** (los que tienen referencia administrativa) por la mediana y por el promedio.
3. **No respuesta:** en lugar de la reponderación del INDEC, se imputa el ingreso del {P(nr['pct_inquilinos_sin_ingreso_declarado'], 0)} de inquilinos que no lo declaró, con imputación múltiple (10 imputaciones, donantes con perfil laboral y demográfico parecido).
"""),
        code(r'''cob = A.cobertura_sipa(con)
sub = A.escenario_subdeclaracion(h, m, cob, base)
nr = K["robustez"]["no_respuesta"]
filas = [
    ("Base: reponderación del INDEC (PONDIH)", K["base"]["elegibles_pct"], *K["base"]["elegibles_ic95"]),
    ("Imputación múltiple de la no respuesta", nr["pct_elegible_imputacion"]["estimacion"], nr["pct_elegible_imputacion"]["ic95_inf"], nr["pct_elegible_imputacion"]["ic95_sup"]),
    ("Sueldos formales corregidos por SIPA (mediana)", sub.pct_elegible.iloc[1], np.nan, np.nan),
    ("Sueldos formales corregidos por SIPA (promedio)", sub.pct_elegible.iloc[2], np.nan, np.nan),
]
r = pd.DataFrame(filas, columns=["escenario", "pct", "inf", "sup"])
fig, ax = plt.subplots(figsize=(10, 2.9))
y = np.arange(len(r))[::-1]
con_ic = r.inf.notna()
ax.errorbar(r.pct[con_ic], y[con_ic], xerr=[r.pct[con_ic] - r.inf[con_ic], r.sup[con_ic] - r.pct[con_ic]], fmt="none", ecolor=viz.BASELINE, elinewidth=2)
ax.scatter(r.pct, y, s=60, color=[viz.INK_2] + [viz.BLUE] * 3, zorder=3, edgecolor=viz.SURFACE, linewidth=1.5)
for yi, rr in zip(y, r.itertuples()):
    ax.text((rr.sup if pd.notna(rr.sup) else rr.pct) + 0.5, yi, fmt_pct(rr.pct), va="center", fontsize=9, color=viz.INK_2)
ax.set_yticks(y, r.escenario); ax.set_xlim(0, 22)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True); ax.xaxis.set_major_formatter(viz.EJE_PCT)
ax.set_title(f"Con otros supuestos, la respuesta va de {fmt_pct(r.pct.min(), 0)} a {fmt_pct(r.pct.max(), 0)}: la conclusión se sostiene")
viz.subtitle(ax, "% de hogares inquilinos elegibles · punto = estimación · línea = IC 95% cuando corresponde")
viz.source(fig, "INDEC EPH, SIPA (remuneraciones), BCRA, Zonaprop Index; elaboración propia.")
viz.save(fig, "03_robustez")
plt.show()
display(cob.round(3)); display(sub.round(3)); pd.json_normalize(nr["validacion"]).T'''),
        md(f"""
**Lectura:** la imputación da {P(nr['pct_elegible_imputacion']['estimacion'])} (IC {D(nr['pct_elegible_imputacion']['ic95_inf'])}–{D(nr['pct_elegible_imputacion']['ic95_sup'])}), un poco menos que la base; en la prueba de validación (se ocultan ingresos conocidos y se imputan) el error promedio fue de {D(nr['validacion']['error_absoluto_medio_pp'])} puntos. Corregir la subdeclaración de sueldos formales sube la elegibilidad a {P(sub[1]['pct_elegible'])}–{P(sub[2]['pct_elegible'])}. **En todos los escenarios, la respuesta sigue siendo "una minoría de los inquilinos": entre 1 de cada 9 y 1 de cada 6.**

## 10. Tablero de hipótesis
"""),
        code(f'''pd.DataFrame([
    ["H1", "Menos del 20% de los inquilinos paga la cuota", "{P(b['pasan_cuota_pct'])} (IC {D(ic_c[0])}–{D(ic_c[1])}); {P(b['elegibles_pct'])} pasa el embudo completo", "{veredicto_h1}"],
    ["H2", "La barrera es el anticipo, no la cuota", "Tope por anticipo {D(h2['precio_max_ingresos_por_anticipo'])} ingresos vs {D(h2['precio_max_ingresos_por_cuota'])} por cuota; {P(h2['pct_fallan_ambos'], 0)} no alcanza ninguna", "Confirmada con matiz"],
    ["H3", "Composición del hogar y elegibilidad", "Parejas sin hijos {P(perfil[('Pareja sin hijos', 'Todas')]['pct_elegible'])}; un solo adulto {P(perfil[('Unipersonal', 'Todas')]['pct_elegible'])}–{P(perfil[('Monoparental', 'Todas')]['pct_elegible'])}", "Hallazgo descriptivo (sin veredicto causal)"],
    ["H4", "La elegibilidad difiere por zona y edad", "Zonas {P(zonas['GBA Norte']['pct_elegible'])}–{P(zonas['GBA Oeste']['pct_elegible'])} (p {D(h4['test_zona']['p_valor'], 2)}); edad p {D(h4['test_edad']['p_valor'], 2)}", "Parcialmente confirmada"],
    ["H5", "Si la UVA le gana a los sueldos, la cuota supera el 30%", "sep-23: 25% → {P(stress[24]['peor_cuota_ingreso_pct'])} a 24 meses", "Confirmada"],
    ["Contexto", "Stock real y tasa se mueven en sentido opuesto", "Correlación débil negativa", "Pasa a contexto de mercado"],
    ["H7", "Tener más de un trabajo mejora el acceso", "Dos personas trabajando {P(trab['2 o más personas trabajando']['pct_elegible'])}; una persona con dos empleos {P(trab['1 persona con 2 o más trabajos']['pct_elegible'])}", "Recuadro: posible punto de fuga"],
], columns=["#", "Hipótesis", "Evidencia", "Veredicto"])'''),
        code("con.close()"),
    ])


# ---------------------------------------------------------------------------
# 04 · Modelo, "¿qué pasa si…?", producto y segmentos
# ---------------------------------------------------------------------------
def nb04():
    pp, lg = K["producto_propuesto"], K["logit"]
    odds = {r["variable"]: r for r in lg["odds_ratios"]}
    qps = {r["pregunta"]: r for r in K["que_pasa_si"]}
    seg = K["segmentos"]
    fgs = K["fgs"]
    b = K["base"]
    return notebook([
        md("""
# 04 · Modelo, "¿qué pasa si…?", producto y segmentos

1. **Complemento de H3:** ¿qué características se asocian a poder pagar? (regresión logística ponderada)
2. **¿Qué pasa si…?** Medidas que puede tomar el banco, en hogares
3. **¿Qué lo empeora?** Riesgos del contexto
4. **Diseño de producto:** plazo × % financiado
5. **Segmentos de "casi elegibles":** a quién apuntar primero
6. **Escala del programa de fondeo**
"""),
        code(BASE_ANALISIS),
        md("## 1. ¿Qué características se asocian a pasar cuota y anticipo?"),
        code(r'''logit, info = A.logit_ponderado(ev)
ETIQ = {
 "dos_o_mas_perceptores": "2 o más personas con ingresos", "educacion_Superior completo": "Jefe/a con superior completo",
 "educacion_Superior incompleto": "Jefe/a con superior incompleto", "educacion_Hasta secundario incompleto": "Jefe/a hasta secundario incompleto",
 "mercado_Gran Córdoba": "Vive en Gran Córdoba", "mercado_CABA": "Vive en CABA",
 "situacion_Cuenta propia / patrón": "Jefe/a cuenta propia o patrón", "situacion_Asalariado informal": "Jefe/a asalariado sin aportes",
 "situacion_No ocupado": "Jefe/a no ocupado",
 "edad_Hasta 29": "Jefe/a hasta 29 años", "edad_40-49": "Jefe/a de 40-49 años", "edad_50-64": "Jefe/a de 50-64 años", "edad_65+": "Jefe/a de 65 años o más",
 "tipo_hogar_Pareja sin hijos": "Pareja sin hijos", "tipo_hogar_Unipersonal": "Hogar unipersonal", "tipo_hogar_Monoparental": "Hogar monoparental",
 "tipo_hogar_Extendido o compuesto": "Hogar extendido o compuesto", "jefatura_mujer": "Figura una mujer como jefa",
}
d = logit.assign(etiqueta=logit.variable.map(ETIQ)).sort_values("odds_ratio")
fig, ax = plt.subplots(figsize=(9.5, 6.4))
ax.axvline(1, color=viz.BASELINE, lw=1)
for i, r in enumerate(d.itertuples()):
    c = viz.BLUE if r.p_valor < 0.05 else viz.CONTEXT_GRAY
    ax.plot([r.or_ic95_inf, r.or_ic95_sup], [i, i], color=c, lw=2, solid_capstyle="round")
    ax.plot(r.odds_ratio, i, "o", color=c, ms=7, mec=viz.SURFACE, mew=1.5)
    if r.p_valor < 0.05:
        ax.text(r.or_ic95_sup * 1.06, i, f"×{fmt_decimal(r.odds_ratio)}", va="center", fontsize=8.5, color=viz.INK_2)
ax.set_yticks(range(len(d)), d.etiqueta)
ax.set_xscale("log")
ax.xaxis.set_major_locator(mtick.FixedLocator([0.25, 0.5, 1, 2, 4, 8]))
ax.xaxis.set_minor_locator(mtick.NullLocator())
ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: "×" + fmt_decimal(v, 2).rstrip("0").rstrip(",")))
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.legend(handles=[Patch(color=viz.BLUE, label="Asociación significativa (p < 0,05)"), Patch(color=viz.CONTEXT_GRAY, label="No significativa")], loc="lower right")
ax.set_title("Estudios superiores y dos ingresos se asocian con más del doble de chances de poder pagar")
viz.subtitle(ax, "Cuánto cambia la chance de pasar cuota + anticipo (odds ratio, escala log) frente al hogar de referencia · IC 95%")
n_obs = f"{info['n_observaciones']:,}".replace(",", ".")
viz.source(fig, f"INDEC EPH; regresión logística ponderada, errores robustos por hogar (n = {n_obs} observaciones, AUC = {fmt_decimal(info['auc_ponderado'], 2)}). Referencia: {info['referencia']}.")
viz.save(fig, "04_logit_odds")
plt.show()
print(info)
d[["etiqueta", "odds_ratio", "or_ic95_inf", "or_ic95_sup", "p_valor"]].sort_values("odds_ratio", ascending=False)'''),
        md(f"""
**Lectura (complemento de H3, asociaciones y no causas):** con las demás características constantes, lo que más se asocia a poder pagar es un **jefe o jefa con superior completo (×{D(odds['educacion_Superior completo']['odds_ratio'])})**, **dos o más personas con ingresos (×{D(odds['dos_o_mas_perceptores']['odds_ratio'])})** y ser **pareja sin hijos (×{D(odds['tipo_hogar_Pareja sin hijos']['odds_ratio'])})**. Vivir en **CABA** reduce la chance (×{D(odds['mercado_CABA']['odds_ratio'])}), por el precio del m².

Que figure una **mujer como jefa** muestra una asociación negativa moderada (×{D(odds['jefatura_mujer']['odds_ratio'])}, IC {D(odds['jefatura_mujer']['or_ic95_inf'], 2)}–{D(odds['jefatura_mujer']['or_ic95_sup'], 2)}). **No debe leerse como un efecto del género:** el modelo no incluye el ingreso (es lo que se busca explicar) ni variables como antigüedad, horas o brechas salariales; ese coeficiente resume diferencias de ingreso que las demás variables no capturan.

> Modelo explicativo, no de scoring individual. AUC {D(lg['info']['auc_ponderado'], 2)}; pesos normalizados; errores robustos por conglomerado (hogar).

## 2. ¿Qué pasa si…? Medidas que puede tomar el banco
**Rediseño pedido en el Checkpoint 3:** la versión anterior mostraba cambios porcentuales por "palanca" y no se entendía. Ahora cada fila es una **pregunta en lenguaje simple**, con **hogares** que se suman o se pierden y **por qué**.
"""),
        code(r'''mejoras, riesgos = A.que_pasa_si(h, m, base)

def grafico_cambios(t, titulo, bajada, archivo, con_por_que=True):
    from matplotlib.transforms import blended_transform_factory
    t = t.sort_values("diferencia").reset_index(drop=True)
    alto = 0.62 * len(t) + 1.5
    fig, ax = plt.subplots(figsize=(11, alto))
    fig.subplots_adjust(left=0.43 if con_por_que else 0.33, right=0.97, top=1 - 0.95 / alto, bottom=0.55 / alto)
    y = np.arange(len(t))
    colores = [viz.BLUE if v > 0.5 else (viz.RED if v < -0.5 else viz.CONTEXT_GRAY) for v in t.diferencia]
    ax.barh(y, t.diferencia, color=colores, height=0.5)
    lo, hi = min(t.diferencia.min(), 0), max(t.diferencia.max(), 0)
    rango = hi - lo
    ax.set_xlim(lo - rango * (0.42 if lo < 0 else 0.03), hi + rango * (0.42 if hi > 0 else 0.03))
    etiquetas = blended_transform_factory(ax.transAxes, ax.transData)
    for yi, r in zip(y, t.itertuples()):
        signo = "+" if r.diferencia > 0.5 else ("−" if r.diferencia < -0.5 else "")
        texto = f"{signo}{fmt_cantidad(abs(r.diferencia))} hogares ({signo}{fmt_pct(abs(r.diferencia_pct), 0)})" if signo else "sin cambio"
        ax.text(r.diferencia + (rango * 0.015 if r.diferencia >= 0 else -rango * 0.015), yi, texto, va="center", ha="left" if r.diferencia >= 0 else "right", fontsize=8.5, color=viz.INK_2)
        ax.text(-0.02, yi + (0.13 if con_por_que else 0), r.pregunta, transform=etiquetas, ha="right", va="center", fontsize=9.5, color=viz.INK)
        if con_por_que:
            ax.text(-0.02, yi - 0.24, r.por_que, transform=etiquetas, ha="right", va="center", fontsize=8, color=viz.MUTED)
    ax.set_yticks([])
    ax.set_ylim(-0.6, len(t) - 0.4)
    ax.axvline(0, color=viz.INK_2, lw=1)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: ("+" if v > 0 else "−" if v < 0 else "") + fmt_cantidad(abs(v))))
    fig.text(0.01, 1 - 0.18 / alto, titulo, fontsize=12, fontweight="semibold", color=viz.INK, ha="left", va="top")
    fig.text(0.01, 1 - 0.50 / alto, bajada, fontsize=9, color=viz.INK_2, ha="left", va="top")
    viz.source(fig, "INDEC EPH, BCRA, Zonaprop Index; elaboración propia.")
    viz.save(fig, archivo)
    plt.show()

base_hog = fmt_cantidad(mejoras.hogares_base.iloc[0])
grafico_cambios(mejoras, "Lo que más suma: atacar el anticipo, el precio o aceptar ingresos de independientes",
                f"Hogares elegibles que se suman o se pierden frente al escenario base ({base_hog} hogares)", "04_que_pasa_si")
grafico_cambios(riesgos, "Lo que más resta: que el anticipo haya que juntarlo más rápido o que suban los precios",
                f"Hogares elegibles que se pierden frente al escenario base ({base_hog} hogares)", "04_que_lo_empeora", con_por_que=False)
display(mejoras); display(riesgos)'''),
        md(f"""
**Lectura:** las medidas que más suman atacan el **efectivo necesario** o el **precio**: una vivienda 20% más barata (+{C(qps['¿Y si se compra una vivienda 20% más barata (usada o más chica)?']['diferencia'])} hogares), aceptar **monotributistas y autónomos con aportes** (+{C(qps['¿Y si acepta monotributistas y autónomos con aportes?']['diferencia'])}), **30 años con 80% financiado** (+{C(qps['¿Y si hace las dos cosas: 30 años y 80%?']['diferencia'])}) o un **plan de ahorro** para el anticipo (+{C(qps['¿Y si un plan de ahorro permite juntar 24 meses de ingreso?']['diferencia'])}). Bajar la tasa o subir el tope de cuota, **solos, no suman**. El plazo largo **solo resta** ({C(qps['¿Y si el banco presta a 30 años en vez de 20?']['diferencia'])}) por la regla de edad.

## 3. Diseño de producto: plazo × % financiado
"""),
        code(r'''grilla = A.grilla_producto(h, m, base)
g = grilla[grilla.tope_cuota_ingreso == 0.25].pivot(index="ltv", columns="plazo_anios", values="pct_elegible").sort_index(ascending=False)
fig, ax = plt.subplots(figsize=(7.5, 4.6))
ax.imshow(g.values, cmap=RAMPA, aspect="auto", vmin=0)
ax.set_xticks(range(g.shape[1]), [f"{c} años" for c in g.columns]); ax.set_yticks(range(g.shape[0]), [fmt_pct(100 * r, 0) for r in g.index])
ax.grid(False)
for s in ax.spines.values(): s.set_visible(False)
vmax = g.values.max()
for i in range(g.shape[0]):
    for j in range(g.shape[1]):
        v = g.values[i, j]
        ax.text(j, i, fmt_pct(v), ha="center", va="center", fontsize=9, color=tinta_sobre(v, 0, vmax))
bi, bj = list(g.index).index(0.75), list(g.columns).index(20)
oi, oj = np.unravel_index(np.nanargmax(g.values), g.shape)
for (i, j, txt) in [(bi, bj, "base"), (oi, oj, "mejor")]:
    ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec=viz.INK, lw=2))
    ax.text(j, i + 0.33, txt, ha="center", va="center", fontsize=7.5, color=tinta_sobre(g.values[i, j], 0, vmax))
ax.set_xlabel("Plazo"); ax.set_ylabel("% financiado")
mejor, base_v = g.values[oi, oj], g.values[bi, bj]
ax.set_title(f"30 años con 80% financiado: +{fmt_pct(100 * (mejor / base_v - 1), 0)} de hogares elegibles")
viz.subtitle(ax, "% de inquilinos elegibles · tasa UVA + 7,5% · tope de cuota 25% (sin subir el riesgo de cuota)")
viz.source(fig, "INDEC EPH, BCRA, Zonaprop Index; elaboración propia.")
viz.save(fig, "04_grilla_plazo_ltv")
plt.show()
grilla.sort_values("hogares", ascending=False).head(8)'''),
        code(r'''prop = base.con(plazo_anios=30, ltv=0.80)
escenarios = {
    "Base: 20 años, 75%": evaluar(h, m, base),
    "Propuesto: 30 años, 80%": evaluar(h, m, prop),
    "Propuesto + monotributistas y autónomos": evaluar(h, m, prop.con(acepta_independientes=True)),
}
tabla = pd.DataFrame({k: {"hogares elegibles": e.peso[e.elegible].sum(), "% de inquilinos": 100 * e.peso[e.elegible].sum() / e.peso.sum()} for k, e in escenarios.items()}).T
tabla["vs base"] = 100 * (tabla["hogares elegibles"] / tabla["hogares elegibles"].iloc[0] - 1)
fig, ax = plt.subplots(figsize=(9, 2.9))
bars = ax.barh(tabla.index[::-1], tabla["hogares elegibles"][::-1], color=[viz.BLUE, viz.BLUE, viz.CONTEXT_GRAY], height=0.6)
for bar, (idx, r) in zip(bars, tabla[::-1].iterrows()):
    extra = "" if idx.startswith("Base") else f" (+{fmt_pct(r['vs base'], 0)})"
    ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2, f"{fmt_cantidad(r['hogares elegibles'])} hogares{extra}", va="center", fontsize=9, color=viz.INK_2)
ax.xaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.set_xlim(0, tabla["hogares elegibles"].max() * 1.35)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.set_title(f"Con el producto propuesto y los independientes, los elegibles pasan de {fmt_cantidad(tabla['hogares elegibles'].iloc[0])} a {fmt_cantidad(tabla['hogares elegibles'].iloc[-1])}")
viz.subtitle(ax, "Hogares inquilinos elegibles por escenario · tope de cuota 25% en todos")
viz.source(fig, "INDEC EPH, BCRA, Zonaprop Index; elaboración propia.")
viz.save(fig, "04_escenarios_producto")
plt.show()
tabla'''),
        md(f"""
**Lectura:** el producto propuesto (**30 años, 80% financiado, cuota hasta 25%**) lleva los elegibles de {C(b['elegibles_hogares'])} a **{C(pp['elegibles_hogares'])} hogares** (+{P(pp['delta_vs_base_pct'], 0)}). Si además se aceptan ingresos de **monotributistas y autónomos con aportes**, llegan a **{C(pp['con_independientes_hogares'])}** (+{P(pp['con_independientes_delta_vs_base_pct'], 0)}), como línea separada con su propia política de riesgo (notebook 05).

## 4. Segmentos de "casi elegibles"
Hogares no elegibles cuyo ingreso cubre **al menos el 60% del ingreso requerido** y cumplen la edad: son el mercado a desarrollar.
"""),
        code(r'''import export_results
casi = A.casi_elegibles(ev)
seg, perfil, sinfo = A.segmentar(casi)
perfil.insert(0, "nombre", perfil.index.map(export_results.nombrar_segmentos(perfil)))
print(f"Casi elegibles: {fmt_hogares(casi.peso.sum())} · k elegido = {sinfo['k_optimo']} · silhouette = { {k: round(v, 2) for k, v in sinfo['silhouette'].items()} }")
fig, ax = plt.subplots(figsize=(9.5, 2.6))
p = perfil.sort_values("hogares")
bars = ax.barh(p.nombre, p.hogares, color=viz.BLUE, height=0.55)
for bar, r in zip(bars, p.itertuples()):
    ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2, f"{fmt_cantidad(r.hogares)} · cubren {fmt_pct(100 * r.cobertura_mediana, 0)} del ingreso requerido", va="center", fontsize=8.5, color=viz.INK_2)
ax.set_xlim(0, p.hogares.max() * 1.8)
ax.xaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.set_title(f"{fmt_cantidad(casi.peso.sum())} hogares están cerca de calificar: {len(p)} perfiles")
viz.subtitle(ax, "Hogares inquilinos no elegibles con ingreso de al menos 60% del requerido · k-means ponderado")
viz.source(fig, "INDEC EPH; elaboración propia.")
viz.save(fig, "04_segmentos")
plt.show()
perfil.T'''),
        md(f"""
**Perfiles** (segmentación exploratoria: silhouette ≈ {D(seg['info']['silhouette'][str(seg['info']['k_optimo'])], 2)} indica estructura débil; se eligió el mayor k con al menos 30 hogares encuestados por grupo. Sirven como guía comercial, no como grupos rígidos):

| Perfil | Hogares | Qué los destraba |
|---|---|---|
""" + "\n".join(
            f"| **{r['nombre']}** | {C(r['hogares'])} · edad mediana {r['edad_mediana']:.0f} · {P(r['pct_formal'], 0)} con aportes · cubren {P(100 * r['cobertura_mediana'], 0)} | "
            + ("Validar ingresos de independientes: ya podrían pagar" if r["pct_formal"] < 5 else
               "Producto 30 años/80% y ahorro programado para el anticipo" if r["pct_2_perceptores"] >= 60 else
               "Vivienda más chica o usada, plan de ahorro y sumar un segundo ingreso") + " |"
            for r in seg["perfil"]) + f"""

## 5. Escala del programa de fondeo
"""),
        code(r'''e = evaluar(h, m, prop)
prestamo_medio = np.average(e.prestamo_ars[e.elegible], weights=e.peso[e.elegible])
fgs = K["fgs"]["monto_ars"]
print(f"Préstamo medio de los elegibles con el producto propuesto: {fmt_monto(prestamo_medio)}")
print(f"El programa ({fmt_monto(fgs)}) financia ~{fmt_cantidad(fgs / prestamo_medio)} créditos")
print(f"Hogares elegibles con el producto propuesto: {fmt_cantidad(e.peso[e.elegible].sum())} → {fmt_decimal(e.peso[e.elegible].sum() / (fgs / prestamo_medio))} veces lo que financia el programa")'''),
        md(f"""
**Lectura:** el programa alcanza para ~{C(fgs['creditos_financiables_aprox'])} créditos (préstamo medio {M(pp['prestamo_medio_elegibles_ars'])}), mientras que hay **{C(pp['elegibles_hogares'])} hogares elegibles** con el producto propuesto ({D(pp['elegibles_hogares'] / fgs['creditos_financiables_aprox'], 0)} veces más). **La demanda elegible alcanza; lo que limita es el fondeo y la velocidad de colocación** (120 días): el banco puede ser selectivo y priorizar los perfiles de menor riesgo.
"""),
        code("con.close()"),
    ])


# ---------------------------------------------------------------------------
# 05 · Independientes (módulo aparte)
# ---------------------------------------------------------------------------
def nb05():
    ind = K["h5"]["independientes"]
    vol = {r["insercion"]: r for r in K["h5"]["volatilidad"]}
    pp = K["producto_propuesto"]
    return notebook([
        md(f"""
# 05 · Módulo independientes: ¿qué pasa con quienes no tienen recibo de sueldo?

**Pregunta del Checkpoint 3:** muchos hogares pueden pagar, pero su ingreso no sale de un recibo de sueldo (monotributistas, autónomos, profesionales que facturan). ¿Cuántos son y qué riesgo agregan?

**Decisión:** analizarlos **en un módulo aparte**, sin modificar la base del estudio (que sigue exigiendo un asalariado con aportes). Así los resultados principales conservan su "pureza" y este módulo muestra el potencial adicional.

**Quiénes cuentan como independientes con aportes** (jefe/a o cónyuge ocupado):
- **Monotributistas** (EPH `PP05I` = 1) y **autónomos** (`PP05I` = 3), entre cuentapropistas y patrones.
- **Asalariados sin descuento jubilatorio que aportan por su cuenta** (`PP07H` = 2 y `PP07I` = 1): el caso típico de quien trabaja en relación de dependencia pero factura.
- El **monotributo social** (`PP05I` = 2) se mide aparte: {'la EPH casi no lo capta en los 3 mercados, así que no se puede estimar con confianza' if ind['inquilinos_con_monotributo_social'] < 5000 else 'se reporta por separado'}.

**Límite declarado:** no existe un índice oficial de ingresos de independientes comparable al de salarios registrados, así que su riesgo de cuota se analiza de forma descriptiva.
"""),
        code(BASE_ANALISIS),
        code(r'''ind = A.modulo_independientes(h, m, base)
pd.Series(ind).to_frame("valor")'''),
        code(r'''filas = [
    ("Inquilinos con jefe/a o cónyuge\nindependiente con aportes", ind["inquilinos_con_independiente_registrado"]),
    ("…sin un asalariado con aportes\nen la pareja", ind["inquilinos_solo_independiente_sin_asalariado_formal"]),
    ("…que pagan la cuota y\njuntan el anticipo", ind["de_ellos_pasan_cuota_y_anticipo"]),
]
fig, ax = plt.subplots(figsize=(9.5, 2.9))
y = np.arange(len(filas))[::-1]
ax.barh(y, [v for _, v in filas], color=["#86b6ef", "#3987e5", "#184f95"], height=0.55)
for yi, (_, v) in zip(y, filas):
    ax.text(v * 1.01 + 2000, yi, fmt_hogares(v), va="center", fontsize=9, color=viz.INK_2)
ax.set_yticks(y, [t for t, _ in filas])
ax.xaxis.set_major_formatter(viz.EJE_CANTIDAD)
ax.set_xlim(0, filas[0][1] * 1.3)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.set_title(f"{fmt_cantidad(ind['de_ellos_pasan_cuota_y_anticipo'])} hogares podrían pagar, pero hoy no califican por no tener recibo de sueldo")
viz.subtitle(ax, "Hogares inquilinos · escenario base (20 años, 75% financiado)")
viz.source(fig, "INDEC EPH (PP05I, PP07H, PP07I); elaboración propia.")
viz.save(fig, "05_independientes_embudo")
plt.show()'''),
        md(f"""
**Lectura:** {C(ind['inquilinos_con_independiente_registrado'])} hogares inquilinos tienen a jefe/a o cónyuge trabajando como independiente con aportes. En {C(ind['inquilinos_solo_independiente_sin_asalariado_formal'])} de ellos **no hay un asalariado con aportes en la pareja**, así que el banco no los ve. De esos, **{C(ind['de_ellos_pasan_cuota_y_anticipo'])} pagan la cuota y juntan el anticipo**. Aceptarlos llevaría los elegibles de {C(ind['elegibles_base'])} a {C(ind['elegibles_aceptando_independientes'])} con el producto base, y de {C(pp['elegibles_hogares'])} a {C(pp['con_independientes_hogares'])} con el producto propuesto. Su ingreso mediano es de {M(ind['ingreso_mediano_de_los_que_se_suman'])} por mes (pesos de agosto de 2026).

## ¿Qué tan estable es su ingreso?
La EPH vuelve a encuestar al mismo hogar en trimestres seguidos. Se compara cuánto cambia el ingreso real del hogar entre dos visitas, según la inserción laboral de jefe/a o cónyuge (todas las tenencias, para tener muestra suficiente).
"""),
        code(r'''vol = A.volatilidad_ingresos(con)
orden = ["Asalariado con aportes", "Independiente con aportes", "Sin aportes (informal o no ocupado)"]
v = vol.set_index("insercion").loc[orden]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 2.8), sharey=True)
y = np.arange(len(v))[::-1]
for ax, col, titulo, bajada in [(a1, "cambio_absoluto_mediano_pct", "Cambio típico entre trimestres", "Mediana del cambio del ingreso real, en valor absoluto"),
                                (a2, "pct_cae_mas_20", "Caídas fuertes", "% de hogares cuyo ingreso real cae más de 20%")]:
    ax.hlines(y, 0, v[col], color=viz.BASELINE, lw=2)
    ax.scatter(v[col], y, s=60, color=[viz.CONTEXT_GRAY, viz.BLUE, viz.CONTEXT_GRAY], zorder=3, edgecolor=viz.SURFACE, linewidth=1.5)
    for yi, val in zip(y, v[col]):
        ax.text(val + 1, yi, fmt_pct(val, 0), va="center", fontsize=9, color=viz.INK_2)
    ax.set_xlim(0, v[col].max() * 1.35); ax.xaxis.set_major_formatter(viz.EJE_PCT)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
    ax.set_title(titulo, fontsize=10.5); viz.subtitle(ax, bajada)
a1.set_yticks(y, [f"{i}\n(n = {n})" for i, n in zip(v.index, v.muestra_hogares)])
viz.titulo_figura(fig, "El ingreso de los independientes varía más entre trimestres, pero la diferencia es moderada")
viz.source(fig, "INDEC EPH, hogares encuestados en dos trimestres seguidos (2T-25 a 1T-26); elaboración propia.")
viz.save(fig, "05_volatilidad_ingresos")
plt.show()
vol.round(1)'''),
        md(f"""
**Lectura:** entre dos trimestres, el ingreso real de un hogar con **asalariado con aportes** cambia típicamente un {P(vol['Asalariado con aportes']['cambio_absoluto_mediano_pct'], 0)}; con **independiente con aportes**, un {P(vol['Independiente con aportes']['cambio_absoluto_mediano_pct'], 0)}. Las caídas de más de 20% afectan al {P(vol['Asalariado con aportes']['pct_cae_mas_20'], 0)} y al {P(vol['Independiente con aportes']['pct_cae_mas_20'], 0)}, respectivamente. Parte de esa variación es error de medición de la encuesta (afecta a todos los grupos por igual), así que lo relevante es la **diferencia**: existe, pero es moderada.

## Implicancias para una línea de independientes
- **Validación de ingresos:** 12 a 24 meses de facturación o de aportes, en lugar de recibo de sueldo.
- **Colchón de riesgo:** cuota hasta 20-25% del ingreso promedio de 12 meses (no del mejor mes) y seguro de desempleo o incapacidad.
- **Seguimiento:** tablero de mora separado para esta línea durante el primer año.
- **Monotributo social:** la EPH no permite dimensionarlo; queda como próximo paso con datos administrativos.
"""),
        code("con.close()"),
    ])



def main() -> None:
    # Sin argumentos arma los seis; con argumentos ("03 04") solo los que empiezan con esos números
    pedidos = sys.argv[1:]
    for nombre, constructor in [("01_exploracion", nb01), ("02_limpieza_calidad", nb02), ("03_analisis_hipotesis", nb03),
                                ("04_modelo_segmentacion_simulador", nb04), ("05_independientes", nb05)]:
        if pedidos and not nombre.startswith(tuple(pedidos)):
            continue
        nbf.write(constructor(), NB_DIR / f"{nombre}.ipynb")
        print(f"  ✓ {nombre}.ipynb")


if __name__ == "__main__":
    main()
