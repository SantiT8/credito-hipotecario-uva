-- =====================================================================
-- 01_staging.sql — Carga cruda (sin transformar) de todas las fuentes
-- Principio: en staging todo entra "como viene" (texto) para poder
-- perfilar los valores sucios antes de decidir cómo limpiarlos.
-- =====================================================================

INSTALL spatial;
LOAD spatial;

-- ---------------------------------------------------------------------
-- EPH (INDEC) — 4 trimestres apilados. Algunos trimestres vienen con
-- comillas y otros sin; se lee todo como VARCHAR y latin-1.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE stg_eph_hogar AS
SELECT *
FROM read_csv('data/raw/eph/usu_hogar_T*.txt',
              delim = ';', header = true, quote = '"', all_varchar = true,
              union_by_name = true, filename = true, encoding = 'latin-1');

CREATE OR REPLACE TABLE stg_eph_individual AS
SELECT *
FROM read_csv('data/raw/eph/usu_individual_T*.txt',
              delim = ';', header = true, quote = '"', all_varchar = true,
              union_by_name = true, filename = true, encoding = 'latin-1');

-- ---------------------------------------------------------------------
-- BCRA API v4.0 — series ya en formato largo (fecha, valor, id, serie)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE stg_bcra AS
SELECT *
FROM read_csv('data/raw/bcra/bcra_*.csv', header = true, all_varchar = true, filename = true);

-- ---------------------------------------------------------------------
-- INDEC Índice de Salarios (API Series de Tiempo)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE stg_salarios AS
SELECT *
FROM read_csv('data/raw/series/indice_salarios.csv', header = true, all_varchar = true);

-- RIPTE: salario formal promedio en pesos corrientes (1994-)
CREATE OR REPLACE TABLE stg_ripte AS
SELECT *
FROM read_csv('data/raw/series/ripte.csv', header = true, all_varchar = true);

-- SIPA: remuneración bruta promedio y mediana de asalariados registrados del sector privado
CREATE OR REPLACE TABLE stg_sipa AS
SELECT *
FROM read_csv('data/raw/series/sipa_remuneraciones.csv', header = true, all_varchar = true);

-- Dólar Banco Nación vendedor (promedio mensual)
CREATE OR REPLACE TABLE stg_dolar_bna AS
SELECT *
FROM read_csv('data/raw/series/dolar_bna_vendedor_mensual.csv', header = true, all_varchar = true);

-- Censo 2022: hogares por régimen de tenencia (tabla ordenada por src/censo.py a partir de los cuadros del INDEC)
CREATE OR REPLACE TABLE stg_censo_hogares AS
SELECT *
FROM read_csv('data/processed/censo2022_hogares_tenencia.csv', header = true);

-- ---------------------------------------------------------------------
-- GCBA Departamentos en venta — el esquema cambia a lo largo de 20 años.
-- Se cargan por "familia" de esquema y se armonizan en 03_clean.sql.
-- ---------------------------------------------------------------------

-- 2001-2014: mismo esquema base (2013 agrega PESOS/PESOS_M2). Separador ';'
-- union_by_name es necesario porque el orden LAT/LON cambia entre años.
-- En 2007 hay 5 filas corridas (16 campos vacíos al inicio, 30 separadores):
-- se lee aparte con store_rejects (incompatible con union_by_name) para que
-- las filas rechazadas queden como evidencia en lugar de perderse en silencio.
CREATE OR REPLACE TABLE stg_gcba_2007 AS
SELECT *
FROM read_csv('data/raw/gcba/departamentos-en-venta-2007.csv',
              delim = ';', header = true, quote = '"', all_varchar = true, filename = true,
              ignore_errors = true, store_rejects = true,
              rejects_table = 'rej_gcba_2007', rejects_scan = 'rej_scan_gcba_2007');

CREATE OR REPLACE TABLE stg_gcba_2001_2014 AS
SELECT *
FROM read_csv(['data/raw/gcba/departamentos-en-venta-2001.csv', 'data/raw/gcba/departamentos-en-venta-2002.csv',
               'data/raw/gcba/departamentos-en-venta-2003.csv', 'data/raw/gcba/departamentos-en-venta-2004.csv',
               'data/raw/gcba/departamentos-en-venta-2005.csv', 'data/raw/gcba/departamentos-en-venta-2006.csv',
               'data/raw/gcba/departamentos-en-venta-2008.csv',
               'data/raw/gcba/departamentos-en-venta-2009.csv', 'data/raw/gcba/departamentos-en-venta-2010.csv',
               'data/raw/gcba/departamentos-en-venta-2011.csv', 'data/raw/gcba/departamentos-en-venta-2012.csv',
               'data/raw/gcba/departamentos-en-venta-2013.csv', 'data/raw/gcba/departamentos-en-venta-2014.csv'],
              delim = ';', header = true, quote = '"', all_varchar = true, union_by_name = true, filename = true)
UNION ALL BY NAME
SELECT * FROM stg_gcba_2007;

DROP TABLE stg_gcba_2007;

-- 2015: esquema extendido, decimales con coma mezclados y campos con espacios
CREATE OR REPLACE TABLE stg_gcba_2015 AS
SELECT *
FROM read_csv('data/raw/gcba/departamentos-en-venta-2015.csv',
              delim = ';', header = true, all_varchar = true, filename = true);

-- 2016: scrapeo de Zonaprop con URL, fechas de publicación y precio en texto
CREATE OR REPLACE TABLE stg_gcba_2016 AS
SELECT *
FROM read_csv('data/raw/gcba/departamentos-en-venta-2016.csv',
              delim = ';', header = true, all_varchar = true, filename = true);

-- 2017-2019: solo shapefile (se lee el .dbf/.shp directo desde el zip)
CREATE OR REPLACE TABLE stg_gcba_2017 AS
SELECT * EXCLUDE (geom), 'Departamentos-en-venta-2017.zip' AS filename
FROM ST_Read('/vsizip/data/raw/gcba/Departamentos-en-venta-2017.zip/Departamentos en Venta 2017/Departamentos_venta_2017.shp');

CREATE OR REPLACE TABLE stg_gcba_2018 AS
SELECT * EXCLUDE (geom), 'Departamentos-en-venta-2018.zip' AS filename
FROM ST_Read('/vsizip/data/raw/gcba/Departamentos-en-venta-2018.zip/Departamentos en Venta 2018/Departamentos_venta_2018.shp');

CREATE OR REPLACE TABLE stg_gcba_2019 AS
SELECT * EXCLUDE (geom), 'Departamentos-en-venta-2019.zip' AS filename
FROM ST_Read('/vsizip/data/raw/gcba/Departamentos-en-venta-2019.zip/Departamentos en venta 2019/Departamentos_venta_2019.shp');

-- 2020: separador ',' y números entre comillas
CREATE OR REPLACE TABLE stg_gcba_2020 AS
SELECT *
FROM read_csv('data/raw/gcba/departamentos-en-venta-2020.csv',
              delim = ',', header = true, quote = '"', all_varchar = true, filename = true);

-- ---------------------------------------------------------------------
-- Referencias curadas: precios Zonaprop (reportes oficiales del índice) y
-- corredores del GBA por partido (31 partidos del aglomerado)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE ref_precios_zonaprop AS
SELECT * FROM read_csv('data/reference/zonaprop_precios_2026.csv', header = true);

CREATE OR REPLACE TABLE ref_gba_partidos AS
SELECT * FROM read_csv('data/reference/gba_partidos_corredor.csv', header = true);

-- Persistir los rechazos (las tablas rej_* de DuckDB son temporales)
CREATE OR REPLACE TABLE stg_rechazos_gcba AS
SELECT s.file_path, e.line, e.error_type, e.error_message, e.csv_line
FROM rej_gcba_2007 e JOIN rej_scan_gcba_2007 s USING (scan_id, file_id);

-- DuckDB registra un error por cada columna sobrante: se muestra una fila por línea rechazada
-- name: rechazos_gcba
SELECT file_path, line, any_value(error_type) AS error_type, count(*) AS errores_registrados,
       left(trim(any_value(csv_line)), 90) AS csv_line
FROM stg_rechazos_gcba GROUP BY file_path, line ORDER BY file_path, line;

-- name: conteo_staging
SELECT 'stg_eph_hogar' AS tabla, count(*) AS filas FROM stg_eph_hogar
UNION ALL SELECT 'stg_eph_individual', count(*) FROM stg_eph_individual
UNION ALL SELECT 'stg_bcra', count(*) FROM stg_bcra
UNION ALL SELECT 'stg_salarios', count(*) FROM stg_salarios
UNION ALL SELECT 'stg_ripte', count(*) FROM stg_ripte
UNION ALL SELECT 'stg_sipa', count(*) FROM stg_sipa
UNION ALL SELECT 'stg_dolar_bna', count(*) FROM stg_dolar_bna
UNION ALL SELECT 'stg_censo_hogares', count(*) FROM stg_censo_hogares
UNION ALL SELECT 'stg_gcba_2001_2014', count(*) FROM stg_gcba_2001_2014
UNION ALL SELECT 'stg_gcba_2015', count(*) FROM stg_gcba_2015
UNION ALL SELECT 'stg_gcba_2016', count(*) FROM stg_gcba_2016
UNION ALL SELECT 'stg_gcba_2017', count(*) FROM stg_gcba_2017
UNION ALL SELECT 'stg_gcba_2018', count(*) FROM stg_gcba_2018
UNION ALL SELECT 'stg_gcba_2019', count(*) FROM stg_gcba_2019
UNION ALL SELECT 'stg_gcba_2020', count(*) FROM stg_gcba_2020
UNION ALL SELECT 'ref_precios_zonaprop', count(*) FROM ref_precios_zonaprop
UNION ALL SELECT 'ref_gba_partidos', count(*) FROM ref_gba_partidos;
