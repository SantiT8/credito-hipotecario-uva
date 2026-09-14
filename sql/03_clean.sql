-- =====================================================================
-- 03_clean.sql — Tablas limpias listas para analizar
-- Depende de: 01_staging.sql y la vista int_gcba_avisos (02_profiling.sql)
-- Cada decisión de limpieza está documentada en reports/01_calidad_datos.md
-- =====================================================================

-- =====================================================================
-- 1. Series mensuales (BCRA + INDEC + RIPTE) en una sola tabla mes a mes
-- =====================================================================
CREATE OR REPLACE TABLE int_series_base AS
WITH bcra AS (
    SELECT serie, CAST(fecha AS DATE) AS fecha, CAST(valor AS DOUBLE) AS valor
    FROM stg_bcra
    WHERE CAST(fecha AS DATE) <= DATE '2026-09-13'          -- fecha de corte (la API publica UVA a futuro)
),
mensual AS (
    SELECT date_trunc('month', fecha) AS mes,
           arg_max(valor, fecha) FILTER (WHERE serie = 'uva')                                 AS uva_fin_mes,
           avg(valor)            FILTER (WHERE serie = 'uva')                                 AS uva_promedio,
           avg(valor)            FILTER (WHERE serie = 'tasa_hipotecaria_uva')                AS tasa_hip_uva,
           avg(valor)            FILTER (WHERE serie = 'tasa_hipotecaria_fija')               AS tasa_hip_fija,
           avg(valor)            FILTER (WHERE serie = 'stock_hipotecarios_personas_humanas') AS stock_hip_millones_ars,
           avg(valor)            FILTER (WHERE serie = 'inflacion_mensual')                   AS inflacion_mensual,
           avg(valor)            FILTER (WHERE serie = 'inflacion_interanual')                AS inflacion_interanual,
           avg(valor)            FILTER (WHERE serie = 'tipo_cambio_minorista')               AS tc_minorista,
           avg(valor)            FILTER (WHERE serie = 'tipo_cambio_mayorista')               AS tc_mayorista,
           -- Destino del crédito hipotecario (saldos; la API los rotula 'miles de ARS' pero la magnitud corresponde a millones, igual que la serie 916)
           avg(valor)            FILTER (WHERE serie = 'hipotecarios_construccion')           AS hip_construccion_millones_ars,
           avg(valor)            FILTER (WHERE serie = 'hipotecarios_refaccion')              AS hip_refaccion_millones_ars,
           avg(valor)            FILTER (WHERE serie = 'hipotecarios_compra_nueva')           AS hip_compra_nueva_millones_ars,
           avg(valor)            FILTER (WHERE serie = 'hipotecarios_compra_usada')           AS hip_compra_usada_millones_ars,
           avg(valor)            FILTER (WHERE serie = 'hipotecarios_otros_destinos')         AS hip_otros_millones_ars
    FROM bcra GROUP BY 1
),
sipa AS (
    SELECT CAST(indice_tiempo AS DATE) AS mes,
           TRY_CAST(asalariados_priv_remuneracion_promedio AS DOUBLE) AS sipa_remuneracion_promedio,
           TRY_CAST(asalariados_priv_remuneracion_mediana AS DOUBLE) AS sipa_remuneracion_mediana
    FROM stg_sipa
),
bna AS (
    SELECT CAST(indice_tiempo AS DATE) AS mes, TRY_CAST(tipo_cambio_bna_vendedor AS DOUBLE) AS tc_bna_vendedor
    FROM stg_dolar_bna
),
calendario AS (
    SELECT CAST(range AS DATE) AS mes FROM range(DATE '2000-01-01', DATE '2026-10-01', INTERVAL 1 MONTH)
),
salarios AS (
    SELECT CAST(indice_tiempo AS DATE) AS mes,
           TRY_CAST(indice_salarios AS DOUBLE) AS indice_salarios_total,
           TRY_CAST(indice_salarios_registrado AS DOUBLE) AS indice_salarios_registrado
    FROM stg_salarios
),
ripte AS (
    SELECT CAST(indice_tiempo AS DATE) AS mes, TRY_CAST(ripte AS DOUBLE) AS ripte
    FROM stg_ripte
),
base AS (
    SELECT c.mes, m.* EXCLUDE (mes), s.indice_salarios_total, s.indice_salarios_registrado, r.ripte,
           sp.sipa_remuneracion_promedio, sp.sipa_remuneracion_mediana, b.tc_bna_vendedor
    FROM calendario c
    LEFT JOIN mensual m USING (mes)
    LEFT JOIN salarios s USING (mes)
    LEFT JOIN ripte r USING (mes)
    LEFT JOIN sipa sp USING (mes)
    LEFT JOIN bna b USING (mes)
)
SELECT *,
       -- IPC encadenado desde la inflación mensual del BCRA
       exp(sum(ln(1 + coalesce(inflacion_mensual, 0) / 100)) OVER (ORDER BY mes)) AS ipc_indice,
       -- Convertibilidad: en 2001 el tipo de cambio oficial era 1 ARS = 1 USD (la serie BCRA empieza 03-2002)
       CASE WHEN mes < DATE '2002-01-01' THEN 1.0 ELSE tc_mayorista END AS tc_mayorista_completo
FROM base
WHERE mes <= DATE '2026-09-01'
ORDER BY mes;

-- Rebase del IPC: pesos constantes de agosto 2026 (último IPC publicado)
CREATE OR REPLACE TABLE series_mensuales AS
WITH base_ipc AS (SELECT ipc_indice AS ipc_ago26 FROM int_series_base WHERE mes = DATE '2026-08-01')
SELECT s.*,
       b.ipc_ago26 / s.ipc_indice AS factor_a_pesos_ago26,
       s.stock_hip_millones_ars * b.ipc_ago26 / s.ipc_indice AS stock_hip_millones_ars_ago26
FROM int_series_base s CROSS JOIN base_ipc b
ORDER BY s.mes;

DROP TABLE int_series_base;

-- =====================================================================
-- 2. Hogares EPH — pool de 4 trimestres (una fila por hogar-trimestre), 3 mercados en alcance
--
-- Corrección del Checkpoint 3: NO se deduplica el panel rotativo. Cada trimestre es una muestra
-- representativa; se apilan los 4 y cada peso se divide por 4, lo que estima el promedio anual sin
-- sesgo. Quedarse con "la visita más reciente" sobrerrepresentaba a los inquilinos (se mudan más y
-- aparecen una sola vez con más frecuencia). Las visitas del mismo hogar se tratan como un
-- conglomerado (hogar_id) al calcular márgenes de error.
-- =====================================================================
CREATE OR REPLACE TABLE hogares_eph AS
WITH h AS (
    SELECT CODUSU AS codusu, CAST(NRO_HOGAR AS INT) AS nro_hogar,
           CAST(ANO4 AS INT) AS anio, CAST(TRIMESTRE AS INT) AS trimestre,
           CAST(ANO4 AS INT) * 10 + CAST(TRIMESTRE AS INT) AS periodo,
           CAST(AGLOMERADO AS INT) AS aglomerado,
           CAST(II7 AS INT) AS tenencia_cod,
           CAST(IX_TOT AS INT) AS miembros,
           CAST(ITF AS DOUBLE) AS itf_nominal,
           CAST(DECIFR AS INT) AS decifr,
           CAST(PONDERA AS DOUBLE) AS pondera,
           CAST(PONDIH AS DOUBLE) AS pondih
    FROM stg_eph_hogar
    WHERE CAST(AGLOMERADO AS INT) IN (32, 33, 13)
),
n_trimestres AS (SELECT count(DISTINCT periodo) AS n FROM h),
ind AS (
    SELECT CODUSU AS codusu, CAST(NRO_HOGAR AS INT) AS nro_hogar, CAST(ANO4 AS INT) * 10 + CAST(TRIMESTRE AS INT) AS periodo,
           CAST(CH03 AS INT) AS parentesco, CAST(CH04 AS INT) AS sexo, CAST(CH06 AS INT) AS edad,
           CAST(NIVEL_ED AS INT) AS nivel_ed, CAST(ESTADO AS INT) AS estado, CAST(CAT_OCUP AS INT) AS cat_ocup,
           CAST(PP07H AS INT) AS pp07h, TRY_CAST(P47T AS DOUBLE) AS p47t, TRY_CAST(P21 AS DOUBLE) AS p21,
           -- PP03C: 1 = un solo empleo, 2 = más de un empleo (solo ocupados); PP03D: cantidad de ocupaciones
           TRY_CAST(PP03C AS INT) AS pp03c, TRY_CAST(PP03D AS INT) AS pp03d,
           -- PP05I (cuenta propia y patrones): aportes como 1 monotributista, 2 monotributista social, 3 autónomo, 4 ninguno
           TRY_CAST(PP05I AS INT) AS pp05i,
           -- PP07I (asalariados sin descuento jubilatorio): ¿aporta por sí mismo a algún sistema jubilatorio? 1 = Sí
           TRY_CAST(PP07I AS INT) AS pp07i,
           TRY_CAST(T_VI AS DOUBLE) AS t_vi                     -- ingresos no laborales (jubilación, subsidios, rentas...)
    FROM stg_eph_individual
),
ind_hogar AS (
    SELECT codusu, nro_hogar, periodo,
           any_value(edad)     FILTER (WHERE parentesco = 1) AS jefe_edad,
           any_value(sexo)     FILTER (WHERE parentesco = 1) AS jefe_sexo,
           any_value(nivel_ed) FILTER (WHERE parentesco = 1) AS jefe_nivel_ed,
           any_value(CASE WHEN estado <> 1 THEN 'No ocupado'
                          WHEN cat_ocup = 3 AND pp07h = 1 THEN 'Asalariado formal'
                          WHEN cat_ocup = 3 THEN 'Asalariado informal'
                          WHEN cat_ocup = 2 THEN 'Cuenta propia'
                          WHEN cat_ocup = 1 THEN 'Patrón'
                          ELSE 'Otro ocupado' END) FILTER (WHERE parentesco = 1) AS jefe_situacion_laboral,
           count(*) FILTER (WHERE parentesco = 2) > 0 AS tiene_conyuge,
           bool_or(estado = 1 AND cat_ocup = 3 AND pp07h = 1) FILTER (WHERE parentesco IN (1, 2)) AS jefe_o_conyuge_formal,
           count(*) FILTER (WHERE p47t > 0) AS perceptores_ingreso,
           count(*) FILTER (WHERE estado = 1) AS personas_ocupadas,
           count(*) FILTER (WHERE estado = 1 AND pp03c = 2) AS personas_con_mas_de_un_trabajo,
           coalesce(sum(CASE WHEN estado = 1 THEN CASE WHEN pp03c = 2 THEN greatest(coalesce(pp03d, 2), 2) ELSE 1 END END), 0) AS trabajos_en_el_hogar,
           coalesce(bool_or(t_vi > 0), false) AS tiene_ingreso_no_laboral,
           -- Ingreso que un banco típicamente computa: solo jefe/a y cónyuge (no hijos ni otros convivientes)
           coalesce(sum(p47t) FILTER (WHERE parentesco IN (1, 2) AND p47t > 0), 0) AS ingreso_titulares_nominal,
           -- Sueldos de asalariados con aportes (ocupación principal): base del escenario de subdeclaración (SIPA)
           coalesce(sum(p21) FILTER (WHERE estado = 1 AND cat_ocup = 3 AND pp07h = 1 AND p21 > 0), 0) AS ingreso_asalariado_formal_nominal,
           -- Módulo independientes (no altera la base): jefe/a o cónyuge con aportes como monotributista o autónomo,
           -- o asalariado sin descuento que aporta por sí mismo (típico empleado que factura)
           coalesce(bool_or(estado = 1 AND ((cat_ocup IN (1, 2) AND pp05i IN (1, 3)) OR (cat_ocup = 3 AND pp07h = 2 AND pp07i = 1)))
                    FILTER (WHERE parentesco IN (1, 2)), false) AS jefe_o_conyuge_indep_registrado,
           coalesce(bool_or(estado = 1 AND cat_ocup IN (1, 2) AND pp05i = 2) FILTER (WHERE parentesco IN (1, 2)), false)
             AS jefe_o_conyuge_monotributo_social,
           -- Composición del hogar (H3)
           count(*) FILTER (WHERE parentesco = 3) AS hijos,
           count(*) FILTER (WHERE parentesco BETWEEN 4 AND 9) AS otros_familiares,
           count(*) FILTER (WHERE parentesco = 10) AS no_familiares
    FROM ind GROUP BY ALL
)
SELECT d.codusu || '-' || d.nro_hogar AS hogar_id,
       d.codusu, d.nro_hogar, d.anio, d.trimestre, d.periodo, d.aglomerado,
       CASE d.aglomerado WHEN 32 THEN 'CABA' WHEN 33 THEN 'Partidos del GBA' WHEN 13 THEN 'Gran Córdoba' END AS mercado,
       d.tenencia_cod,
       CASE WHEN d.tenencia_cod IN (1, 2) THEN 'Propietario' WHEN d.tenencia_cod = 3 THEN 'Inquilino' ELSE 'Otra situación' END AS tenencia,
       d.miembros,
       d.decifr <> 12 AS ingreso_declarado,
       d.itf_nominal,
       -- Ingreso llevado a pesos de ago-26 con el IPC del mes central del trimestre de referencia
       d.itf_nominal * s.factor_a_pesos_ago26 AS itf_real_ago26,
       i.ingreso_titulares_nominal * s.factor_a_pesos_ago26 AS ingreso_titulares_ago26,
       i.ingreso_asalariado_formal_nominal * s.factor_a_pesos_ago26 AS ingreso_asalariado_formal_ago26,
       d.itf_nominal * s.factor_a_pesos_ago26 / nullif(d.miembros, 0) AS ingreso_por_persona_ago26,
       d.itf_nominal * s.factor_a_pesos_ago26 / nullif(i.perceptores_ingreso, 0) AS ingreso_por_perceptor_ago26,
       -- Pool: peso de hogares y peso de ingresos del INDEC divididos por la cantidad de trimestres
       d.pondera / nt.n AS pondera_ajust,
       d.pondih / nt.n AS pondih_ajust,
       i.jefe_edad, i.jefe_sexo, i.jefe_nivel_ed, i.jefe_situacion_laboral,
       i.tiene_conyuge, coalesce(i.jefe_o_conyuge_formal, false) AS hogar_formal, i.perceptores_ingreso,
       i.personas_ocupadas, i.personas_con_mas_de_un_trabajo, i.trabajos_en_el_hogar, i.tiene_ingreso_no_laboral,
       i.jefe_o_conyuge_indep_registrado, i.jefe_o_conyuge_monotributo_social,
       i.hijos, i.otros_familiares, i.no_familiares,
       CASE WHEN d.miembros = 1 THEN 'Unipersonal'
            WHEN i.otros_familiares > 0 OR i.no_familiares > 0 THEN 'Extendido o compuesto'
            WHEN i.tiene_conyuge AND i.hijos = 0 THEN 'Pareja sin hijos'
            WHEN i.tiene_conyuge AND i.hijos > 0 THEN 'Pareja con hijos'
            WHEN NOT i.tiene_conyuge AND i.hijos > 0 THEN 'Monoparental'
            ELSE 'Extendido o compuesto' END AS tipo_hogar,
       CASE WHEN i.jefe_edad < 30 THEN '18-29' WHEN i.jefe_edad < 40 THEN '30-39' WHEN i.jefe_edad < 50 THEN '40-49'
            WHEN i.jefe_edad < 65 THEN '50-64' ELSE '65+' END AS tramo_edad_jefe
FROM h d
CROSS JOIN n_trimestres nt
JOIN ind_hogar i USING (codusu, nro_hogar, periodo)
JOIN series_mensuales s ON s.mes = make_date(d.anio, d.trimestre * 3 - 1, 1)   -- mes central: feb/may/ago/nov
WHERE d.tenencia_cod BETWEEN 1 AND 9;                                             -- II7 = 0 no es código válido

-- =====================================================================
-- 3. Avisos GCBA 2001-2020 — armonizados y limpios
-- =====================================================================
CREATE OR REPLACE TABLE ref_barrios_caba AS
SELECT * FROM (VALUES
 ('AGRONOMIA'), ('ALMAGRO'), ('BALVANERA'), ('BARRACAS'), ('BELGRANO'), ('BOCA'), ('BOEDO'), ('CABALLITO'),
 ('CHACARITA'), ('COGHLAN'), ('COLEGIALES'), ('CONSTITUCION'), ('FLORES'), ('FLORESTA'), ('LINIERS'), ('MATADEROS'),
 ('MONTE CASTRO'), ('MONTSERRAT'), ('NUEVA POMPEYA'), ('NUNEZ'), ('PALERMO'), ('PARQUE AVELLANEDA'), ('PARQUE CHACABUCO'),
 ('PARQUE CHAS'), ('PARQUE PATRICIOS'), ('PATERNAL'), ('PUERTO MADERO'), ('RECOLETA'), ('RETIRO'), ('SAAVEDRA'),
 ('SAN CRISTOBAL'), ('SAN NICOLAS'), ('SAN TELMO'), ('VELEZ SARSFIELD'), ('VERSALLES'), ('VILLA CRESPO'),
 ('VILLA DEL PARQUE'), ('VILLA DEVOTO'), ('VILLA GRAL. MITRE'), ('VILLA LUGANO'), ('VILLA LURO'), ('VILLA ORTUZAR'),
 ('VILLA PUEYRREDON'), ('VILLA REAL'), ('VILLA RIACHUELO'), ('VILLA SANTA RITA'), ('VILLA SOLDATI'), ('VILLA URQUIZA')
) t(barrio);

-- Se materializa con un id estable: row_number() OVER () sin orden no es determinístico
-- y un CTE referenciado dos veces puede numerar distinto en cada evaluación.
CREATE OR REPLACE TABLE int_gcba_base AS
SELECT row_number() OVER (ORDER BY anio, familia_esquema, direccion, barrio_raw, m2, precio_usd, ambientes, lat_raw, lon_raw) AS fila_id, *
FROM int_gcba_avisos;

CREATE OR REPLACE TABLE int_gcba_flags AS
WITH b AS (
    SELECT *,
           -- Normalización de barrio: mayúsculas, sin acentos, mojibake de Ñ, truncados y sub-barrios 2019-20
           CASE
             WHEN upper(trim(barrio_raw)) LIKE 'NU%EZ' THEN 'NUNEZ'
             ELSE regexp_replace(regexp_replace(
                    strip_accents(upper(trim(barrio_raw))),
                    '^MONSERRAT$', 'MONTSERRAT'),
                    '^(BARRACAS|FLORES|VILLA DEVOTO) (ESTE|OESTE|NORTE|SUR)$', '\1')
           END AS barrio_norm
    FROM int_gcba_base
),
b2 AS (
    SELECT * REPLACE (
             CASE barrio_norm WHEN 'VILLA GRAL. MITR' THEN 'VILLA GRAL. MITRE'
                              WHEN 'PARQUE AVELLANED' THEN 'PARQUE AVELLANEDA' ELSE barrio_norm END AS barrio_norm),
           -- 2001: columnas LAT y LON invertidas en el origen
           CASE WHEN anio = 2001 THEN lon_raw ELSE lat_raw END AS lat_fix,
           CASE WHEN anio = 2001 THEN lat_raw ELSE lon_raw END AS lon_fix
    FROM b
),
f AS (
    SELECT *,
           precio_usd / nullif(m2, 0) AS usd_m2,
           (coalesce(operacion, 'VTA') <> 'VTA'
             OR coalesce(tipo, '') IN ('EDIFICIO', 'TIPO CASA', 'PETIT HOTEL', 'CHALET'))  AS r1_no_es_venta_depto,
           (precio_usd IS NULL OR precio_usd <= 0 OR m2 IS NULL OR m2 < 15 OR m2 > 500) AS r2_precio_o_m2_invalido,
           (barrio_norm IS NULL OR barrio_norm NOT IN (SELECT barrio FROM ref_barrios_caba)) AS r3_barrio_invalido
    FROM b2
),
d AS (
    SELECT *,
           row_number() OVER (PARTITION BY anio, upper(coalesce(direccion, '')), barrio_norm, m2, precio_usd, ambientes
                              ORDER BY fila_id) > 1 AS r4_duplicado
    FROM f
    WHERE NOT r1_no_es_venta_depto AND NOT r2_precio_o_m2_invalido AND NOT r3_barrio_invalido
),
limites AS (
    -- Outliers de precio/m²: Tukey extremo (k = 3) sobre ln(USD/m²) por año
    SELECT anio,
           quantile_cont(ln(usd_m2), 0.25) AS q1, quantile_cont(ln(usd_m2), 0.75) AS q3
    FROM d WHERE NOT r4_duplicado GROUP BY anio
)
SELECT f.*,
       coalesce(d.r4_duplicado, false) AS r4_duplicado,
       -- (CASE evita ln(0) en filas ya descartadas por r2: DuckDB no cortocircuita el AND)
       coalesce(NOT d.r4_duplicado AND CASE WHEN f.usd_m2 > 0 THEN
                  ln(f.usd_m2) < l.q1 - 3 * (l.q3 - l.q1) OR ln(f.usd_m2) > l.q3 + 3 * (l.q3 - l.q1) END, false)
         AS r5_outlier_usd_m2
FROM f
LEFT JOIN d USING (fila_id)
LEFT JOIN limites l ON l.anio = f.anio;

CREATE OR REPLACE TABLE avisos_caba AS
SELECT anio, barrio_norm AS barrio, m2, ambientes, precio_usd, usd_m2,
       CASE WHEN lat_fix BETWEEN -34.75 AND -34.5 AND lon_fix BETWEEN -58.6 AND -58.3 THEN lat_fix END AS lat,
       CASE WHEN lat_fix BETWEEN -34.75 AND -34.5 AND lon_fix BETWEEN -58.6 AND -58.3 THEN lon_fix END AS lon,
       familia_esquema
FROM int_gcba_flags
WHERE NOT (r1_no_es_venta_depto OR r2_precio_o_m2_invalido OR r3_barrio_invalido OR r4_duplicado OR r5_outlier_usd_m2);

-- =====================================================================
-- 4. Precios de referencia (Zonaprop, reportes oficiales del índice)
--
-- GBA abierto (Checkpoint 3): la EPH no identifica partido, así que el GBA se trabaja como una
-- grilla de 31 partidos. Cada partido tiene su precio Zonaprop y su peso = hogares inquilinos según
-- el Censo 2022. Los 5 partidos periurbanos sin precio propio usan el precio ponderado de su corredor.
-- =====================================================================
CREATE OR REPLACE TABLE ref_precios_gba_partido AS
WITH alq AS (
    SELECT nombre AS partido, alquilada AS hogares_alquilados_censo, hogares AS hogares_censo
    FROM stg_censo_hogares WHERE nivel = 'partido' AND provincia = 'Buenos Aires'
),
precio AS (
    SELECT nombre AS partido, usd_m2 AS usd_m2_propio FROM ref_precios_zonaprop WHERE nivel = 'municipio'
),
base AS (
    SELECT p.partido, p.corredor, p.en_24_partidos, a.hogares_censo, a.hogares_alquilados_censo, pr.usd_m2_propio
    FROM ref_gba_partidos p
    LEFT JOIN alq a USING (partido)
    LEFT JOIN precio pr USING (partido)
),
corredor AS (
    SELECT corredor,
           sum(usd_m2_propio * hogares_alquilados_censo) FILTER (WHERE usd_m2_propio IS NOT NULL)
             / sum(hogares_alquilados_censo) FILTER (WHERE usd_m2_propio IS NOT NULL) AS usd_m2_corredor_ponderado
    FROM base GROUP BY 1
)
SELECT b.partido, b.corredor, b.en_24_partidos, b.hogares_censo, b.hogares_alquilados_censo,
       coalesce(b.usd_m2_propio, c.usd_m2_corredor_ponderado) AS usd_m2,
       b.usd_m2_propio IS NULL AS precio_imputado_por_corredor,
       b.hogares_alquilados_censo / sum(b.hogares_alquilados_censo) OVER () AS peso_en_gba,
       b.hogares_alquilados_censo / sum(b.hogares_alquilados_censo) OVER (PARTITION BY b.corredor) AS peso_en_corredor
FROM base b JOIN corredor c USING (corredor)
ORDER BY b.corredor, b.partido;

CREATE OR REPLACE TABLE ref_precios_mercado AS
SELECT mercado, usd_m2, periodo, fuente FROM ref_precios_zonaprop WHERE nivel = 'mercado'
UNION ALL
SELECT 'Partidos del GBA', sum(usd_m2 * peso_en_gba), '2026-07',
       'Zonaprop por municipio, ponderado por hogares inquilinos del Censo 2022 (referencia; el cálculo usa la grilla por partido)'
FROM ref_precios_gba_partido;

-- name: validacion_precios_gba
SELECT coalesce(corredor, 'Total GBA') AS corredor, count(*) AS partidos,
       sum(precio_imputado_por_corredor::INT) AS partidos_sin_precio_propio,
       sum(hogares_alquilados_censo) AS hogares_inquilinos_censo,
       round(100 * sum(peso_en_gba), 1) AS pct_de_inquilinos_gba,
       -- precio ponderado por inquilinos dentro del grupo (válido también para la fila total)
       round(sum(usd_m2 * hogares_alquilados_censo) / sum(hogares_alquilados_censo)) AS usd_m2_ponderado_inquilinos,
       min(usd_m2) AS usd_m2_min, max(usd_m2) AS usd_m2_max
FROM ref_precios_gba_partido GROUP BY ROLLUP (corredor) ORDER BY grouping(corredor), corredor;

-- name: validacion_partidos_sin_match
SELECT partido FROM ref_precios_gba_partido WHERE hogares_alquilados_censo IS NULL;

-- =====================================================================
-- 5. Evidencia de la limpieza (embudo) y validaciones post-limpieza
-- =====================================================================

-- name: gcba_embudo_limpieza
SELECT anio, count(*) AS avisos_crudos,
       sum(r1_no_es_venta_depto::INT) AS r1_no_venta_depto,
       sum((NOT r1_no_es_venta_depto AND r2_precio_o_m2_invalido)::INT) AS r2_precio_m2_invalido,
       sum((NOT r1_no_es_venta_depto AND NOT r2_precio_o_m2_invalido AND r3_barrio_invalido)::INT) AS r3_barrio_invalido,
       sum(r4_duplicado::INT) AS r4_duplicados,
       sum(r5_outlier_usd_m2::INT) AS r5_outliers,
       count(*) - sum((r1_no_es_venta_depto OR r2_precio_o_m2_invalido OR r3_barrio_invalido OR r4_duplicado OR r5_outlier_usd_m2)::INT) AS avisos_limpios,
       round(100.0 * (count(*) - sum((r1_no_es_venta_depto OR r2_precio_o_m2_invalido OR r3_barrio_invalido OR r4_duplicado OR r5_outlier_usd_m2)::INT)) / count(*), 1) AS pct_conservado
FROM int_gcba_flags GROUP BY anio ORDER BY anio;

-- name: validacion_avisos_limpios
SELECT count(*) AS avisos, count(DISTINCT barrio) AS barrios_distintos,
       min(m2) AS m2_min, max(m2) AS m2_max, round(min(usd_m2)) AS usd_m2_min, round(max(usd_m2)) AS usd_m2_max,
       sum((lat IS NULL)::INT) AS sin_coordenadas_validas
FROM avisos_caba;

-- name: validacion_hogares_eph
SELECT mercado,
       count(*) AS observaciones_hogar_trimestre,
       count(DISTINCT hogar_id) AS hogares_distintos,
       round(sum(pondera_ajust)) AS hogares_expandidos,
       round(sum(pondih_ajust)) AS hogares_expandidos_pondih,
       round(sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino')) AS inquilinos_expandidos,
       count(*) FILTER (WHERE tenencia = 'Inquilino' AND ingreso_declarado) AS observaciones_inquilinos_con_ingreso,
       round(100.0 * sum(pondera_ajust) FILTER (WHERE NOT ingreso_declarado) / sum(pondera_ajust), 1) AS pct_sin_ingreso_declarado,
       sum((jefe_edad IS NULL)::INT) AS sin_jefe,
       round(100.0 * sum(pondera_ajust) FILTER (WHERE tenencia = 'Inquilino') / sum(pondera_ajust), 1) AS pct_inquilinos
FROM hogares_eph GROUP BY ROLLUP (mercado) ORDER BY mercado NULLS LAST;

-- El pool debe reproducir el promedio trimestral de la encuesta (control de la corrección del Checkpoint 3)
-- name: validacion_pool_vs_promedio_trimestral
WITH trimestral AS (
    SELECT CAST(AGLOMERADO AS INT) AS aglomerado, sum(CAST(PONDERA AS DOUBLE)) FILTER (WHERE II7 = '3') AS inquilinos
    FROM stg_eph_hogar WHERE CAST(AGLOMERADO AS INT) IN (32, 33, 13) GROUP BY ANO4, TRIMESTRE, 1
)
SELECT round((SELECT sum(inquilinos) FROM trimestral) / 4) AS inquilinos_promedio_trimestral,
       round((SELECT sum(pondera_ajust) FROM hogares_eph WHERE tenencia = 'Inquilino')) AS inquilinos_pool;

-- Composición de los hogares inquilinos (H3) y cobertura del módulo de independientes
-- name: validacion_composicion_inquilinos
WITH total AS (SELECT sum(pondera_ajust) AS t FROM hogares_eph WHERE tenencia = 'Inquilino')
SELECT coalesce(tipo_hogar, 'Total inquilinos') AS tipo_hogar,
       round(sum(pondera_ajust)) AS hogares,
       round(100.0 * sum(pondera_ajust) / any_value(total.t), 1) AS pct,
       round(100.0 * sum(pondera_ajust) FILTER (WHERE jefe_sexo = 2) / sum(pondera_ajust), 1) AS pct_jefatura_mujer,
       round(100.0 * sum(pondera_ajust) FILTER (WHERE jefe_o_conyuge_indep_registrado) / sum(pondera_ajust), 1) AS pct_con_independiente_registrado
FROM hogares_eph CROSS JOIN total WHERE tenencia = 'Inquilino'
GROUP BY ROLLUP (tipo_hogar) ORDER BY grouping(tipo_hogar), hogares DESC;

-- Mediana ponderada del ingreso familiar (pesos corrientes del trimestre) para comparar con INDEC
-- name: validacion_mediana_itf_por_trimestre
WITH h AS (
    SELECT CAST(ANO4 AS INT) * 10 + CAST(TRIMESTRE AS INT) AS periodo, CAST(ITF AS DOUBLE) AS itf, CAST(PONDIH AS DOUBLE) AS w
    FROM stg_eph_hogar WHERE CAST(PONDIH AS DOUBLE) > 0
), o AS (
    SELECT periodo, itf, w, sum(w) OVER (PARTITION BY periodo ORDER BY itf) AS acum, sum(w) OVER (PARTITION BY periodo) AS total FROM h
)
SELECT periodo, min(itf) FILTER (WHERE acum >= total / 2) AS mediana_itf_ponderada_31_aglomerados,
       round(avg(itf)) AS media_simple_sin_ponderar
FROM o GROUP BY periodo ORDER BY periodo;

-- Sanity check contra INDEC "Evolución de la distribución del ingreso (EPH) 1T-2026":
-- población 30,1 M · mediana IPCF $500.000 · media IPCF $728.008 (Gini 0,442 se valida en notebook 02)
-- name: validacion_vs_indec_1t2026
WITH p AS (
    SELECT TRY_CAST(replace(IPCF, ',', '.') AS DOUBLE) AS ipcf, CAST(PONDIH AS DOUBLE) AS w, CAST(PONDERA AS DOUBLE) AS pondera
    FROM stg_eph_individual WHERE ANO4 = '2026' AND TRIMESTRE = '1'
), o AS (
    SELECT ipcf, w, sum(w) OVER (ORDER BY ipcf ROWS UNBOUNDED PRECEDING) AS acum, sum(w) OVER () AS total FROM p WHERE w > 0
)
SELECT round((SELECT sum(pondera) FROM p) / 1e6, 1) AS poblacion_millones_calc, 30.1 AS poblacion_indec,
       min(ipcf) FILTER (WHERE acum >= total / 2) AS mediana_ipcf_calc, 500000 AS mediana_ipcf_indec,
       round(sum(ipcf * w) / sum(w)) AS media_ipcf_calc, 728008 AS media_ipcf_indec
FROM o;

-- name: validacion_series_ultimo_dato
SELECT max(mes) FILTER (WHERE uva_fin_mes IS NOT NULL) AS ultimo_mes_uva,
       arg_max(uva_fin_mes, mes) FILTER (WHERE uva_fin_mes IS NOT NULL) AS uva_ultimo,
       max(mes) FILTER (WHERE tasa_hip_uva IS NOT NULL) AS ultimo_mes_tasa, arg_max(tasa_hip_uva, mes) FILTER (WHERE tasa_hip_uva IS NOT NULL) AS tasa_uva_ultima,
       max(mes) FILTER (WHERE ripte IS NOT NULL) AS ultimo_mes_ripte,
       max(mes) FILTER (WHERE indice_salarios_registrado IS NOT NULL) AS ultimo_mes_salarios,
       round(arg_max(factor_a_pesos_ago26, mes) FILTER (WHERE mes = DATE '2025-05-01'), 3) AS factor_may25_a_ago26
FROM series_mensuales;
