"""Configuración central del proyecto: rutas, fecha de corte, fuentes y supuestos validados.

Todos los scripts y notebooks importan desde acá para que las cifras sean consistentes
entre el análisis, el dashboard, los documentos y el deck.
"""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REFERENCE = ROOT / "data" / "reference"
PROCESSED = ROOT / "data" / "processed"
SQL_DIR = ROOT / "sql"
FIGURES = ROOT / "reports" / "figures"
DB_PATH = PROCESSED / "hipotecario.duckdb"

# Fecha de corte de datos de mercado. La API del BCRA publica la UVA con fechas futuras.
FECHA_CORTE = date(2026, 9, 13)

# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) credito-hipotecario-uva/1.0"}

# EPH: últimos 4 trimestres publicados (trimestre, año). Convención de nombres vigente: EPH_usu_{t}_Trim_{año}_txt.zip
EPH_TRIMESTRES = [(2, 2025), (3, 2025), (4, 2025), (1, 2026)]
EPH_URL = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/EPH_usu_{t}_Trim_{y}_txt.zip"
EPH_REGISTRO_URL = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/EPH_registro_{t}T{y}.pdf"

# Mercados en alcance (Checkpoint 3): se quita Gran Rosario; el GBA se abre por partido y corredor
AGLOMERADOS = {32: "CABA", 33: "Partidos del GBA", 13: "Gran Córdoba"}
MERCADOS = list(AGLOMERADOS.values())
CORREDORES_GBA = ["Norte", "Oeste", "Sur"]

# BCRA API Estadísticas v4.0
BCRA_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{id}"
BCRA_SERIES = {
    31: "uva",
    1240: "tasa_hipotecaria_uva",
    1217: "tasa_hipotecaria_fija",
    916: "stock_hipotecarios_personas_humanas",
    27: "inflacion_mensual",
    28: "inflacion_interanual",
    4: "tipo_cambio_minorista",
    5: "tipo_cambio_mayorista",   # desde 2002-03; en 2001 rige convertibilidad (1 ARS = 1 USD)
    # Destino del crédito hipotecario (saldos; la API rotula "miles" pero los valores están en millones de ARS)
    1113: "hipotecarios_construccion",
    1114: "hipotecarios_refaccion",
    1115: "hipotecarios_compra_nueva",
    1116: "hipotecarios_compra_usada",
    1117: "hipotecarios_otros_destinos",
}

# API de Series de Tiempo (datos.gob.ar)
SERIES_URL = "https://apis.datos.gob.ar/series/api/series/"
SERIES_IDS = {
    "149.1_TL_INDIIOS_OCTU_0_21": "indice_salarios_total",       # INDEC, base oct-2016 = 100
    "149.1_TL_REGIADO_OCTU_0_16": "indice_salarios_registrado",  # INDEC, base oct-2016 = 100
}
# RIPTE (salario formal promedio, pesos corrientes, 1994-)
RIPTE_ID = "158.1_REPTE_0_0_5"
# SIPA: remuneración bruta de asalariados registrados del sector privado (promedio y mediana, mensual)
SIPA_IDS = {"153.1_RNERACIDIO_2009_M_21": "sipa_remuneracion_promedio", "153.1_RNERACIANA_2009_M_20": "sipa_remuneracion_mediana"}
# Tipo de cambio Banco Nación, vendedor (diario → promedio mensual)
BNA_ID = "168.1_T_CAMBIOR_D_0_0_26"
# Aportes personales del trabajador en relación de dependencia: 11% jubilación + 3% PAMI + 3% obra social
APORTES_TRABAJADOR = 0.17

# GCBA — Departamentos en venta (avisos 2001-2020)
GCBA_PACKAGE_URL = "https://data.buenosaires.gob.ar/api/3/action/package_show?id=departamentos-venta"

# Censo 2022 (INDEC, resultados definitivos): hogares por régimen de tenencia
CENSO_BASE_URL = "https://censo.gob.ar/wp-content/uploads/"
CENSO_ARCHIVOS = {
    "c2022_tp_hogares_c6.xlsx": "2023/11/",
    "c2022_bsas_hogares_c6_2.xlsx": "2023/11/",
    "c2022_caba_hogares_c6_1.xlsx": "2023/11/",
    "c2022_cordoba_hogares_c6_6.xlsx": "2023/11/",
}

# ---------------------------------------------------------------------------
# Supuestos del producto — escenario base (Checkpoints 1 y 2)
# ---------------------------------------------------------------------------
BASE = {
    "tna": 0.075,              # tasa nominal anual sobre UVA (tope del programa de fondeo)
    "plazo_anios": 20,
    "ltv": 0.75,               # % financiado
    "tope_cuota_ingreso": 0.25,
    "gastos_compra": 0.07,     # escritura + sellos + comisión, sobre el precio
    "tope_prestamo_uva": 150_000,
    "meses_ingreso_anticipo": 12,  # anticipo + gastos <= N ingresos mensuales
    "requiere_ingreso_formal": True,  # jefe/a o cónyuge asalariado con aportes
    "edad_max_fin_credito": 85,       # Banco Nación: cancelación hasta los 85 años inclusive
}


# m² de vivienda de referencia según cantidad de integrantes (IX_TOT).
# Checkpoint 3: no es una regla fija; H1 se muestra como mapa de calor sobre un rango de m².
def m2_por_hogar(miembros: int) -> int:
    if miembros <= 2:
        return 45
    if miembros <= 4:
        return 60
    return 75
