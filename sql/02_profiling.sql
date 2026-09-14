-- =====================================================================
-- 02_profiling.sql — Perfilado de calidad de datos (evidencia)
-- Cada query "-- name:" se guarda en data/processed/evidencia/02_profiling/
-- y alimenta reports/01_calidad_datos.md.
-- =====================================================================

-- =====================================================================
-- A. EPH — hogares
-- =====================================================================

-- name: eph_hogares_por_trimestre
SELECT ANO4 AS anio, TRIMESTRE AS trimestre, count(*) AS hogares,
       sum(TRY_CAST(PONDERA AS BIGINT)) AS hogares_expandidos_pondera,
       sum(TRY_CAST(PONDIH AS BIGINT)) AS hogares_expandidos_pondih
FROM stg_eph_hogar GROUP BY ALL ORDER BY anio, trimestre;

-- Clave natural por trimestre: CODUSU + NRO_HOGAR (+ período). Debe ser única.
-- name: eph_duplicados_clave_trimestre
SELECT count(*) AS filas, count(DISTINCT (CODUSU, NRO_HOGAR, ANO4, TRIMESTRE)) AS claves_distintas,
       count(*) - count(DISTINCT (CODUSU, NRO_HOGAR, ANO4, TRIMESTRE)) AS duplicados
FROM stg_eph_hogar;

-- Panel rotativo 2-2-2: el mismo hogar aparece en varios trimestres.
-- name: eph_panel_repeticiones
WITH apariciones AS (
    SELECT CODUSU, NRO_HOGAR, count(*) AS veces FROM stg_eph_hogar GROUP BY ALL
)
SELECT veces AS trimestres_en_que_aparece, count(*) AS hogares_distintos,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM apariciones GROUP BY 1 ORDER BY 1;

-- Régimen de tenencia (II7): 0 no es un código válido del diseño de registro
-- name: eph_tenencia_codigos
SELECT II7 AS codigo, CASE II7
         WHEN '1' THEN 'Propietario vivienda y terreno' WHEN '2' THEN 'Propietario solo vivienda'
         WHEN '3' THEN 'Inquilino' WHEN '4' THEN 'Ocupante por impuestos/expensas'
         WHEN '5' THEN 'Ocupante en relación de dependencia' WHEN '6' THEN 'Ocupante gratuito'
         WHEN '7' THEN 'Ocupante de hecho' WHEN '8' THEN 'En sucesión' WHEN '9' THEN 'Otra situación'
         ELSE '⚠ código inválido/sin dato' END AS descripcion,
       count(*) AS hogares
FROM stg_eph_hogar GROUP BY ALL ORDER BY codigo;

-- No respuesta de ingresos: DECIFR = 12 ⇒ ITF = 0 y PONDIH = 0
-- name: eph_no_respuesta_ingresos
SELECT CASE WHEN DECIFR = '12' THEN 'No respuesta (decil 12)'
            WHEN DECIFR = '0' OR DECIFR = '00' THEN 'Sin ingresos (decil 0)'
            ELSE 'Con ingreso declarado (deciles 1-10)' END AS situacion,
       count(*) AS hogares,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct,
       sum((TRY_CAST(ITF AS DOUBLE) = 0)::INT) AS con_itf_cero,
       sum((TRY_CAST(PONDIH AS INT) = 0)::INT) AS con_pondih_cero
FROM stg_eph_hogar GROUP BY 1 ORDER BY 1;

-- name: eph_itf_nulos_no_numericos
SELECT sum((ITF IS NULL OR trim(ITF) = '')::INT) AS itf_vacios,
       sum((ITF IS NOT NULL AND trim(ITF) <> '' AND TRY_CAST(ITF AS DOUBLE) IS NULL)::INT) AS itf_no_numericos,
       sum((TRY_CAST(ITF AS DOUBLE) < 0)::INT) AS itf_negativos,
       sum((TRY_CAST(IX_TOT AS INT) IS NULL OR TRY_CAST(IX_TOT AS INT) < 1)::INT) AS miembros_invalidos
FROM stg_eph_hogar;

-- Alcance (Checkpoint 3): CABA, Partidos del GBA y Gran Córdoba. Gran Rosario queda fuera.
-- name: eph_hogares_en_alcance
SELECT AGLOMERADO AS aglomerado, CASE AGLOMERADO WHEN '32' THEN 'CABA' WHEN '33' THEN 'Partidos del GBA'
         WHEN '13' THEN 'Gran Córdoba' END AS mercado,
       count(*) AS filas_4_trimestres, count(DISTINCT (CODUSU, NRO_HOGAR)) AS hogares_distintos,
       count(*) FILTER (WHERE II7 = '3') AS filas_inquilinos,
       round(sum(TRY_CAST(PONDERA AS DOUBLE)) / 4) AS hogares_expandidos_promedio_trimestral
FROM stg_eph_hogar WHERE AGLOMERADO IN ('32', '33', '13') GROUP BY ALL ORDER BY filas_4_trimestres DESC;

-- =====================================================================
-- B. EPH — individuos
-- =====================================================================

-- Integridad: cada hogar debe tener exactamente 1 jefe/a (CH03 = 1)
-- name: eph_jefes_por_hogar
WITH j AS (
    SELECT CODUSU, NRO_HOGAR, ANO4, TRIMESTRE, sum((CH03 = '1')::INT) AS jefes
    FROM stg_eph_individual GROUP BY ALL
)
SELECT jefes AS cantidad_jefes, count(*) AS hogares FROM j GROUP BY 1 ORDER BY 1;

-- Integridad referencial hogar ↔ individuos
-- name: eph_integridad_hogar_individuo
SELECT
  (SELECT count(*) FROM stg_eph_hogar h WHERE NOT EXISTS (
       SELECT 1 FROM stg_eph_individual i WHERE i.CODUSU = h.CODUSU AND i.NRO_HOGAR = h.NRO_HOGAR
         AND i.ANO4 = h.ANO4 AND i.TRIMESTRE = h.TRIMESTRE)) AS hogares_sin_individuos,
  (SELECT count(*) FROM stg_eph_individual i WHERE NOT EXISTS (
       SELECT 1 FROM stg_eph_hogar h WHERE i.CODUSU = h.CODUSU AND i.NRO_HOGAR = h.NRO_HOGAR
         AND i.ANO4 = h.ANO4 AND i.TRIMESTRE = h.TRIMESTRE)) AS individuos_sin_hogar;

-- Formalidad: PP07H (descuento jubilatorio) solo aplica a asalariados ocupados
-- name: eph_formalidad_asalariados
SELECT CASE PP07H WHEN '1' THEN 'Con descuento jubilatorio (formal)'
                  WHEN '2' THEN 'Sin descuento jubilatorio (informal)'
                  ELSE 'Otro código: ' || coalesce(PP07H, 'NULL') END AS pp07h,
       count(*) AS asalariados_ocupados,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM stg_eph_individual WHERE ESTADO = '1' AND CAT_OCUP = '3' GROUP BY 1 ORDER BY 2 DESC;

-- Códigos especiales en edad e ingreso individual
-- name: eph_codigos_especiales_individuos
SELECT sum((CH06 = '-1')::INT) AS edad_menor_1_anio_cod_menos1,
       sum((TRY_CAST(CH06 AS INT) > 100)::INT) AS edad_mayor_100,
       sum((TRY_CAST(P47T AS DOUBLE) = -9)::INT) AS ingreso_individual_no_respuesta_menos9,
       round(100.0 * sum((TRY_CAST(P47T AS DOUBLE) = -9)::INT) / count(*), 1) AS pct_ingreso_nr
FROM stg_eph_individual;

-- Consistencia: ITF debería ser la suma de P47T (>0) de los miembros
-- name: eph_consistencia_itf_vs_suma_individual
WITH s AS (
    SELECT CODUSU, NRO_HOGAR, ANO4, TRIMESTRE,
           sum(CASE WHEN TRY_CAST(P47T AS DOUBLE) > 0 THEN TRY_CAST(P47T AS DOUBLE) ELSE 0 END) AS suma_p47t,
           bool_or(TRY_CAST(P47T AS DOUBLE) = -9) AS algun_nr
    FROM stg_eph_individual GROUP BY ALL
)
SELECT CASE WHEN h.DECIFR = '12' THEN 'Hogar no respuesta'
            WHEN abs(TRY_CAST(h.ITF AS DOUBLE) - s.suma_p47t) <= 1 THEN 'ITF = suma individual'
            ELSE 'ITF ≠ suma individual' END AS resultado,
       count(*) AS hogares
FROM stg_eph_hogar h JOIN s USING (CODUSU, NRO_HOGAR, ANO4, TRIMESTRE)
GROUP BY 1 ORDER BY 2 DESC;

-- =====================================================================
-- C. BCRA y salarios
-- =====================================================================

-- name: bcra_cobertura_series
SELECT serie, id_variable, count(*) AS observaciones, min(fecha) AS desde, max(fecha) AS hasta,
       count(*) - count(DISTINCT fecha) AS fechas_duplicadas,
       sum((TRY_CAST(valor AS DOUBLE) IS NULL)::INT) AS valores_no_numericos,
       sum((TRY_CAST(fecha AS DATE) > DATE '2026-09-13')::INT) AS fechas_futuras
FROM stg_bcra GROUP BY ALL ORDER BY serie;

-- Huecos en series mensuales (meses faltantes entre desde y hasta)
-- name: bcra_huecos_mensuales
WITH m AS (
    SELECT serie, date_trunc('month', TRY_CAST(fecha AS DATE)) AS mes FROM stg_bcra
    WHERE serie IN ('tasa_hipotecaria_uva', 'tasa_hipotecaria_fija', 'stock_hipotecarios_personas_humanas',
                    'inflacion_mensual', 'inflacion_interanual')
), r AS (SELECT serie, min(mes) AS d, max(mes) AS h, count(DISTINCT mes) AS meses FROM m GROUP BY 1)
SELECT serie, d AS desde, h AS hasta, meses AS meses_con_dato,
       datediff('month', d, h) + 1 AS meses_esperados,
       datediff('month', d, h) + 1 - meses AS meses_faltantes
FROM r ORDER BY serie;

-- name: salarios_cobertura
SELECT min(indice_tiempo) AS desde, max(indice_tiempo) AS hasta, count(*) AS meses,
       sum((indice_salarios IS NULL)::INT) AS total_nulos,
       min(indice_tiempo) FILTER (WHERE indice_salarios IS NOT NULL) AS total_desde,
       sum((indice_salarios_registrado IS NULL)::INT) AS registrado_nulos
FROM stg_salarios;

-- =====================================================================
-- D. GCBA avisos — vista de armonización de esquema (sin filtrar nada)
-- 5 familias de esquema en 20 años → columnas comunes para perfilar igual
-- =====================================================================
CREATE OR REPLACE VIEW int_gcba_avisos AS
SELECT CAST(regexp_extract(filename, '(\d{4})') AS INT) AS anio,
       NULL::VARCHAR AS operacion, NULL::VARCHAR AS tipo,
       trim(CALLE) || ' ' || trim(NUMERO) AS direccion,
       TRY_CAST(M2 AS DOUBLE) AS m2,
       TRY_CAST(DOLARES AS DOUBLE) AS precio_usd,
       TRY_CAST(replace(U_S_M2, ',', '.') AS DOUBLE) AS usd_m2_reportado,
       TRY_CAST(AMBIENTES AS DOUBLE) AS ambientes,
       BARRIO AS barrio_raw, COMUNA AS comuna_raw,
       TRY_CAST(LAT AS DOUBLE) AS lat_raw, TRY_CAST(LON AS DOUBLE) AS lon_raw,
       '2001-2014' AS familia_esquema
FROM stg_gcba_2001_2014
UNION ALL
SELECT 2015, NULL, trim(EDIFICACION), trim(CALLE) || ' ' || trim(NUMERO),
       TRY_CAST(trim(M2) AS DOUBLE), TRY_CAST(trim(DOLARES) AS DOUBLE),
       TRY_CAST(replace(trim(U_S_M2), ',', '.') AS DOUBLE), TRY_CAST(trim(AMBIENTES) AS DOUBLE),
       BARRIOS, COMUNA, TRY_CAST(LATITUD AS DOUBLE), TRY_CAST(LONGITUD AS DOUBLE), '2015'
FROM stg_gcba_2015
UNION ALL
SELECT 2016, OPERACION, TIPO, trim(DIRECCION), TRY_CAST(M2 AS DOUBLE), TRY_CAST(DOLARES AS DOUBLE),
       TRY_CAST(U_S_M2 AS DOUBLE), TRY_CAST(AMBIENTES AS DOUBLE), BARRIO, COMUNA,
       TRY_CAST(LATITUD AS DOUBLE), TRY_CAST(LONGITUD AS DOUBLE), '2016'
FROM stg_gcba_2016
UNION ALL
SELECT 2017, NULL, NULL, NULL, M2TOTAL, PRECIOUSD, PRECIOUSDM, AMBIENTES, BARRIO, CAST(Comuna AS VARCHAR),
       NULL, NULL, '2017-shp'
FROM stg_gcba_2017
UNION ALL
SELECT 2018, OPERACION, TIPO, trim(DIRECCION), M2TOTAL, PRECIOUSD, PRECIOUSDM, AMBIENTES, BARRIO_1,
       CAST(COMUNA_1 AS VARCHAR), LATITUD, LONGITUD, '2018-shp'
FROM stg_gcba_2018
UNION ALL
SELECT 2019, OPERACION, TIPO, trim(DIRECCION), M2TOTAL, PRECIOUSD, PRECIOUSDM, AMBIENTES, BARRIOS_1,
       CAST(COMUNAS AS VARCHAR), LATITUD, LONGITUD, '2019-shp'
FROM stg_gcba_2019
UNION ALL
SELECT 2020, NULL, NULL, trim(Direccion), TRY_CAST(PropiedadS AS DOUBLE), TRY_CAST(Dolares AS DOUBLE),
       TRY_CAST(DolaresM2 AS DOUBLE), TRY_CAST(Ambientes AS DOUBLE), Barrio, Comunas, NULL, NULL, '2020'
FROM stg_gcba_2020;

-- name: gcba_resumen_por_anio
SELECT anio, familia_esquema, count(*) AS avisos,
       sum((precio_usd IS NULL OR precio_usd <= 0)::INT) AS precio_nulo_o_cero,
       sum((m2 IS NULL OR m2 <= 0)::INT) AS m2_nulo_o_cero,
       sum((barrio_raw IS NULL OR trim(barrio_raw) = '')::INT) AS sin_barrio,
       sum((coalesce(operacion, 'VTA') <> 'VTA' OR coalesce(tipo, 'DTO') NOT IN ('DTO', 'DUPLEX', 'TRIPLEX', 'PH', ''))::INT) AS no_venta_o_no_depto
FROM int_gcba_avisos GROUP BY ALL ORDER BY anio;

-- Duplicados exactos dentro del año (misma dirección, m², precio y ambientes)
-- name: gcba_duplicados_por_anio
WITH k AS (
    SELECT anio, upper(coalesce(direccion, '')) AS dir, m2, precio_usd, ambientes, count(*) AS n
    FROM int_gcba_avisos GROUP BY ALL
)
SELECT anio, sum(n) AS avisos, sum(n) - count(*) AS duplicados,
       round(100.0 * (sum(n) - count(*)) / sum(n), 1) AS pct_duplicados
FROM k GROUP BY anio ORDER BY anio;

-- U$S/m² reportado vs calculado (precio / m²): inconsistencias > 5%
-- name: gcba_usd_m2_inconsistente
SELECT anio, count(*) AS con_ambos_valores,
       sum((abs(usd_m2_reportado - precio_usd / m2) / (precio_usd / m2) > 0.05)::INT) AS difieren_mas_5pct
FROM int_gcba_avisos WHERE precio_usd > 0 AND m2 > 0 AND usd_m2_reportado > 0
GROUP BY anio ORDER BY anio;

-- Distribución para definir outliers con criterio de dominio
-- name: gcba_percentiles_m2_usdm2
SELECT anio,
       quantile_cont(m2, [0.001, 0.01, 0.5, 0.99, 0.999]) AS m2_p01_1_50_99_999,
       quantile_cont(precio_usd / m2, [0.001, 0.01, 0.5, 0.99, 0.999]) AS usd_m2_p01_1_50_99_999,
       sum((m2 < 15)::INT) AS m2_menor_15, sum((m2 > 500)::INT) AS m2_mayor_500,
       sum((precio_usd / m2 < 300)::INT) AS usd_m2_menor_300, sum((precio_usd / m2 > 15000)::INT) AS usd_m2_mayor_15000
FROM int_gcba_avisos WHERE precio_usd > 0 AND m2 > 0 GROUP BY anio ORDER BY anio;

-- Coordenadas fuera de CABA o invertidas (lat ≈ -34,6 / lon ≈ -58,4)
-- name: gcba_coordenadas_invalidas
SELECT anio,
       sum((lat_raw BETWEEN -58.6 AND -58.3 AND lon_raw BETWEEN -34.75 AND -34.5)::INT) AS lat_lon_invertidas,
       sum((lat_raw IS NOT NULL AND NOT (lat_raw BETWEEN -34.75 AND -34.5) AND NOT (lat_raw BETWEEN -58.6 AND -58.3))::INT) AS fuera_de_rango,
       sum((lat_raw IS NULL)::INT) AS sin_coordenadas
FROM int_gcba_avisos GROUP BY anio ORDER BY anio;

-- Variantes de escritura de barrios (CABA tiene 48 barrios oficiales)
-- name: gcba_barrios_variantes
SELECT upper(trim(barrio_raw)) AS barrio_tal_cual, count(*) AS avisos, min(anio) AS primer_anio, max(anio) AS ultimo_anio
FROM int_gcba_avisos GROUP BY 1 ORDER BY 1;
