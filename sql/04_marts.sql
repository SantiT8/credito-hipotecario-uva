-- =====================================================================
-- 04_marts.sql — Agregados de series para análisis, dashboard y deck
-- (La elegibilidad por hogar depende de parámetros de producto y se calcula
--  en src/affordability.py; acá van los marts que no dependen de supuestos.)
-- =====================================================================

-- ---------------------------------------------------------------------
-- H6 · Mercado de crédito: stock real y tasa UVA, con crecimiento a 12 meses
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_mercado_credito AS
SELECT mes,
       stock_hip_millones_ars_ago26 / 1e6 AS stock_real_billones_ago26,
       tasa_hip_uva,
       100 * (stock_hip_millones_ars_ago26 / lag(stock_hip_millones_ars_ago26, 12) OVER (ORDER BY mes) - 1) AS crecimiento_real_12m_pct,
       -- 2022-07 a 2024-06: casi sin otorgamientos → tasa promedio poco representativa (ver calidad B5)
       mes >= DATE '2022-07-01' AND mes < DATE '2024-07-01' AS periodo_bajo_volumen
FROM series_mensuales
-- La tasa llega hasta ago-26 y el stock hasta jun-26: se conservan ambos hasta su último dato
WHERE mes >= DATE '2016-05-01' AND (stock_hip_millones_ars_ago26 IS NOT NULL OR tasa_hip_uva IS NOT NULL)
ORDER BY mes;

-- name: mercado_credito_hitos
SELECT
  (SELECT strftime(arg_max(mes, stock_real_billones_ago26), '%Y-%m') FROM mart_mercado_credito) AS mes_pico,
  (SELECT round(max(stock_real_billones_ago26), 2) FROM mart_mercado_credito) AS stock_pico_billones,
  (SELECT strftime(arg_min(mes, stock_real_billones_ago26), '%Y-%m') FROM mart_mercado_credito) AS mes_minimo,
  (SELECT round(min(stock_real_billones_ago26), 2) FROM mart_mercado_credito) AS stock_minimo_billones,
  (SELECT strftime(max(mes), '%Y-%m') FROM mart_mercado_credito WHERE stock_real_billones_ago26 IS NOT NULL) AS mes_ultimo,
  (SELECT round(arg_max(stock_real_billones_ago26, mes), 2) FROM mart_mercado_credito WHERE stock_real_billones_ago26 IS NOT NULL) AS stock_ultimo_billones,
  (SELECT round(100 * arg_max(stock_real_billones_ago26, mes) / max(stock_real_billones_ago26), 1) FROM mart_mercado_credito WHERE stock_real_billones_ago26 IS NOT NULL) AS pct_del_pico,
  (SELECT strftime(max(mes), '%Y-%m') FROM mart_mercado_credito WHERE tasa_hip_uva IS NOT NULL) AS mes_ultima_tasa,
  (SELECT round(arg_max(tasa_hip_uva, mes), 2) FROM mart_mercado_credito WHERE tasa_hip_uva IS NOT NULL) AS tasa_uva_ultima;

-- ---------------------------------------------------------------------
-- H5 · Stress test UVA vs salarios registrados
-- Deudor que empieza con cuota = 25% del ingreso en el mes "inicio":
--   cuota/ingreso(t) = 25% × (UVA_t / UVA_inicio) / (Salario_t / Salario_inicio)
-- (sistema francés en UVA: la cuota en UVAs es constante; el ingreso sigue al índice de salarios)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_stress_uva_salarios AS
WITH base AS (
    SELECT mes, uva_promedio, indice_salarios_registrado
    FROM series_mensuales
    WHERE uva_promedio IS NOT NULL AND indice_salarios_registrado IS NOT NULL
)
SELECT i.mes AS inicio, datediff('month', i.mes, t.mes) AS meses_transcurridos, t.mes,
       0.25 * (t.uva_promedio / i.uva_promedio) / (t.indice_salarios_registrado / i.indice_salarios_registrado) AS cuota_ingreso
FROM base i JOIN base t ON t.mes BETWEEN i.mes AND i.mes + INTERVAL 36 MONTH;

-- name: stress_resumen_ventanas
SELECT meses_transcurridos AS horizonte_meses,
       count(*) AS ventanas,
       round(100 * max(cuota_ingreso), 1) AS peor_cuota_ingreso_pct,
       strftime(arg_max(inicio, cuota_ingreso), '%Y-%m') AS inicio_peor_ventana,
       round(100 * min(cuota_ingreso), 1) AS mejor_cuota_ingreso_pct,
       strftime(arg_min(inicio, cuota_ingreso), '%Y-%m') AS inicio_mejor_ventana,
       round(100 * avg((cuota_ingreso > 0.30)::INT), 1) AS pct_ventanas_sobre_30
FROM mart_stress_uva_salarios WHERE meses_transcurridos IN (12, 24, 36)
GROUP BY 1 ORDER BY 1;

-- Trayectoria de episodios elegidos (para gráfico): créditos iniciados en may-2018 y sep-2023
-- name: stress_episodios
SELECT strftime(inicio, '%Y-%m') AS inicio, meses_transcurridos, round(100 * cuota_ingreso, 1) AS cuota_ingreso_pct
FROM mart_stress_uva_salarios
WHERE inicio IN (DATE '2018-05-01', DATE '2023-09-01') AND meses_transcurridos % 6 = 0
ORDER BY inicio, meses_transcurridos;

-- ---------------------------------------------------------------------
-- Contexto histórico · ¿cuántos m² de CABA compra un salario formal (RIPTE)?
-- 2001-2020: mediana de avisos GCBA limpios · 2026: Zonaprop Index (otra metodología)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_m2_por_salario AS
WITH precios AS (
    SELECT anio, median(usd_m2) AS usd_m2_mediana, count(*) AS avisos, 'GCBA avisos (mediana)' AS fuente_precio
    FROM avisos_caba GROUP BY anio
    UNION ALL
    SELECT 2026, usd_m2, NULL, 'Zonaprop Index jul-26 (promedio)' FROM ref_precios_mercado WHERE mercado = 'CABA'
),
anual AS (
    SELECT year(mes) AS anio, avg(ripte) AS ripte_promedio, avg(tc_mayorista_completo) AS tc_promedio,
           count(ripte) AS meses_ripte
    FROM series_mensuales GROUP BY 1
)
SELECT p.anio, p.fuente_precio, p.avisos, p.usd_m2_mediana, a.ripte_promedio, a.tc_promedio,
       a.ripte_promedio / a.tc_promedio AS ripte_usd,
       (a.ripte_promedio / a.tc_promedio) / p.usd_m2_mediana AS m2_por_salario,
       60 * p.usd_m2_mediana * a.tc_promedio / (13 * a.ripte_promedio) AS anios_de_salario_60m2
FROM precios p JOIN anual a USING (anio)
ORDER BY p.anio;

-- name: m2_por_salario
SELECT anio, fuente_precio, round(usd_m2_mediana) AS usd_m2, round(ripte_usd) AS salario_usd,
       round(m2_por_salario, 2) AS m2_por_salario, round(anios_de_salario_60m2, 1) AS anios_salario_60m2
FROM mart_m2_por_salario ORDER BY anio;

-- ---------------------------------------------------------------------
-- H5 · El sueldo en tres lentes: pesos corrientes, dólares (BNA vendedor) y poder de compra (IPC)
-- Sueldo = remuneración bruta mediana de asalariados registrados del sector privado (SIPA).
-- Se usa la mediana: el promedio se infla con bonos y aguinaldo (junio y diciembre).
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_sueldo_tres_lentes AS
WITH base AS (
    SELECT mes, sipa_remuneracion_mediana AS sueldo_bruto, sipa_remuneracion_promedio,
           tc_bna_vendedor, ipc_indice, uva_promedio, factor_a_pesos_ago26
    FROM series_mensuales
    WHERE mes >= DATE '2016-04-01' AND sipa_remuneracion_mediana IS NOT NULL AND tc_bna_vendedor IS NOT NULL
      AND month(mes) NOT IN (6, 12)                         -- meses con aguinaldo
),
ref AS (SELECT * FROM base WHERE mes = (SELECT min(mes) FROM base))
SELECT b.mes,
       b.sueldo_bruto,
       b.sueldo_bruto / b.tc_bna_vendedor AS sueldo_usd_bna,
       b.sueldo_bruto * b.factor_a_pesos_ago26 AS sueldo_real_pesos_ago26,
       100 * b.sueldo_bruto / r.sueldo_bruto AS indice_sueldo,
       100 * b.ipc_indice / r.ipc_indice AS indice_ipc,
       100 * b.uva_promedio / r.uva_promedio AS indice_uva,
       100 * (b.sueldo_bruto / b.ipc_indice) / (r.sueldo_bruto / r.ipc_indice) AS indice_sueldo_real
FROM base b CROSS JOIN ref r
ORDER BY b.mes;

-- name: sueldo_tres_lentes_hitos
SELECT strftime(mes, '%Y-%m') AS mes, round(sueldo_bruto) AS sueldo_bruto_mediano,
       round(sueldo_usd_bna) AS sueldo_usd_bna, round(sueldo_real_pesos_ago26) AS sueldo_real_ago26
FROM mart_sueldo_tres_lentes
WHERE mes IN (DATE '2017-11-01', DATE '2018-05-01', DATE '2019-11-01', DATE '2023-09-01', DATE '2023-11-01', DATE '2024-05-01',
              DATE '2025-05-01', (SELECT max(mes) FROM mart_sueldo_tres_lentes))
ORDER BY mes;

-- ---------------------------------------------------------------------
-- Contexto · ¿Para qué se usa el crédito hipotecario? (saldos por destino, BCRA)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_destino_credito AS
SELECT mes,
       hip_compra_usada_millones_ars * factor_a_pesos_ago26 / 1e6 AS compra_usada_billones_ago26,
       hip_compra_nueva_millones_ars * factor_a_pesos_ago26 / 1e6 AS compra_nueva_billones_ago26,
       hip_construccion_millones_ars * factor_a_pesos_ago26 / 1e6 AS construccion_billones_ago26,
       hip_refaccion_millones_ars * factor_a_pesos_ago26 / 1e6 AS refaccion_billones_ago26,
       hip_otros_millones_ars * factor_a_pesos_ago26 / 1e6 AS otros_billones_ago26
FROM series_mensuales
WHERE hip_compra_usada_millones_ars IS NOT NULL AND mes >= DATE '2016-01-01'
ORDER BY mes;

-- name: destino_credito_ultimo
SELECT strftime(mes, '%Y-%m') AS mes,
       round(compra_usada_billones_ago26, 2) AS compra_usada, round(compra_nueva_billones_ago26, 2) AS compra_nueva,
       round(construccion_billones_ago26, 2) AS construccion, round(refaccion_billones_ago26, 2) AS refaccion,
       round(otros_billones_ago26, 2) AS otros,
       round(100 * compra_usada_billones_ago26 / (compra_usada_billones_ago26 + compra_nueva_billones_ago26 + construccion_billones_ago26
             + refaccion_billones_ago26 + otros_billones_ago26), 1) AS pct_compra_usada
FROM mart_destino_credito WHERE mes IN ((SELECT max(mes) FROM mart_destino_credito), DATE '2018-05-01', DATE '2024-06-01')
ORDER BY mes;
