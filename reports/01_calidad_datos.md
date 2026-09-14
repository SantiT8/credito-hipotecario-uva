# 01 · Calidad de datos: problemas, evidencia y decisiones

> **Estado:** validado en el Checkpoint 2 y actualizado con las correcciones del Checkpoint 3 (pool de trimestres, alcance de 3 mercados, GBA por partido, Censo 2022, SIPA y dólar BNA).
>
> **Cómo reproducir:**
> 1. `src/download.py`
> 2. `notebooks/01_exploracion.ipynb`
> 3. `notebooks/02_limpieza_calidad.ipynb`
>
> **Evidencia:** cada fila de este reporte sale de una query con nombre en `sql/0X_*.sql`, cuyo resultado queda guardado en `data/processed/evidencia/`.

**Regla del proyecto:** ninguna fila se descarta en silencio. Cada filtro tiene un conteo, una justificación y su impacto.

---

## Resumen ejecutivo

| Fuente | Filas crudas | Filas limpias | Qué cambió |
|---|---|---|---|
| **EPH hogares (4 trimestres, 31 aglomerados)** | 63.010 | **13.175 observaciones** de 8.784 hogares en los 3 mercados | Pool de 4 trimestres (ponderadores / 4); filtro de alcance; ingresos a pesos de ago-26 |
| **EPH individuos** | 178.474 | agregados al hogar (jefe/a, cónyuge, formalidad) | Integridad 100%: 1 jefe por hogar, 0 huérfanos |
| **Series BCRA (13) + Índice de Salarios + RIPTE + SIPA + dólar BNA** | 16.784 + 129 + 385 + 378 + 141 | **321 meses** (2000-01 a 2026-09) | Filtro de fecha de corte; IPC encadenado; convertibilidad 2001; unidades del destino del crédito corregidas |
| **Censo 2022 (hogares por tenencia)** | 5 cuadros Excel | **222 filas** (país, provincias, comunas, partidos, departamentos) | Formato ordenado; control: suma de partidos = total provincial |
| **Zonaprop Index** | 3 reportes | **31 precios** (CABA, Córdoba, 3 corredores y 26 partidos) | Carga desde los reportes oficiales, con URL y período |
| **Avisos GCBA 2001-2020** | 580.327 (+5 líneas rechazadas) | **449.050 (77,4%)** | 5 esquemas armonizados; 124.888 duplicados; barrios normalizados; outliers |

**La validación clave pasó.** Recalculando desde los microdatos las cifras oficiales del INDEC para el 1T-2026, **todas coinciden exactamente**:

| Indicador | Calculado desde microdatos | Publicado por INDEC |
|---|---|---|
| Población | 30,1 M | 30,1 M |
| Mediana del ingreso per cápita familiar (IPCF) | $500.000 | $500.000 |
| Media del IPCF | $728.008 | $728.008 |
| Gini | 0,442 | 0,442 |

Eso confirma que la lectura, los códigos y los ponderadores están bien.

---

## A. EPH (INDEC)

| # | Problema | Evidencia | Decisión | Impacto |
|---|---|---|---|---|
| E1 | **Formato distinto entre trimestres**: 4T-25 viene sin comillas, el resto con comillas. Además, decimales con coma en `IPCF` (`276666,67`) | `01_staging` | Leer todo como texto con `quote='"'` y convertir con `replace(',', '.')` | 0 filas perdidas |
| E2 | **No respuesta de ingresos**: 15.493 hogares (24,6%) con decil 12, `ITF = 0` y `PONDIH = 0` | `eph_no_respuesta_ingresos` | Todo cálculo de ingresos usa `PONDIH`, el ponderador del INDEC que redistribuye el peso de los no respondentes. **Control (Checkpoint 3):** imputación múltiple por PMM (`src/imputacion.py`) como escenario alternativo. | En los 3 mercados: 37% de los hogares sin ingreso declarado (GBA 41%, CABA 37%, Córdoba 10%) |
| E3 | **Hogares sin ingresos reales** (decil 0): 325 hogares con `ITF = 0` y `PONDIH > 0` | `eph_no_respuesta_ingresos` | Se conservan: son hogares reales sin ingresos, no un error | Cuentan como "no elegibles" |
| E4 | **Panel rotativo 2-2-2**: el 56,3% de los hogares distintos aparece en 2 trimestres | `eph_panel_repeticiones` | **Corrección del Checkpoint 3:** la primera versión deduplicaba quedándose con la aparición más reciente, lo que sobrerrepresentaba a los inquilinos (se mudan más y aparecen una vez). Se reemplazó por un **pool**: todas las visitas, con `hogar_id` como conglomerado para los márgenes de error | 13.175 observaciones de 8.784 hogares |
| E5 | **Suma de ponderadores del pool**: al juntar trimestres, la suma excede la población | `validacion_pool_vs_promedio_trimestral` | Dividir `PONDERA` y `PONDIH` por la cantidad de trimestres (4): el total expandido es el **promedio trimestral** | CABA 1,3 millones · GBA 4,1 millones · Córdoba 605 mil hogares; inquilinos del pool = promedio trimestral (1,2 millones) |
| E6 | **Código de tenencia inválido** (`II7 = 0`): 33 hogares en total | `eph_tenencia_codigos` | Excluir: no se puede clasificar como inquilino o propietario | 7 observaciones en los 3 mercados |
| E7 | **Ingresos en pesos corrientes de trimestres distintos**, con inflación de ~1,5-3% mensual | `validacion_series_ultimo_dato` | Llevar a **pesos de ago-26** con el IPC encadenado (BCRA serie 27), usando el mes central del trimestre | Factor may-25 → ago-26 = 1,409 |
| E8 | **Códigos especiales en individuos**: edad `-1` (menores de 1 año: 1.058), ingreso individual `-9` (no respuesta: 12,2%) | `eph_codigos_especiales_individuos` | `-1` se trata como edad 0. `-9` no se suma al ingreso (`P47T > 0`) | Solo afecta los agregados del hogar |
| OK | **Integridad verificada** | `eph_jefes_por_hogar`, `eph_integridad_hogar_individuo`, `eph_consistencia_itf_vs_suma_individual` | Sin acción | 1 jefe por hogar en 63.010 casos · 0 huérfanos · ITF = suma de los ingresos individuales en el 100% de los respondentes |
| E9 | **Nivel de inquilinos frente al Censo 2022** | `validacion_censo/comparacion_eph_censo` | Validación con los cuadros oficiales del Censo y **rango ajustado** para cantidades absolutas | La EPH capta 2,4 a 4,4 puntos menos de inquilinos (CABA 34,4% vs 36,8%; GBA 15,3% vs 17,8%; Córdoba 29,9% vs 34,3%). Factor de ajuste 1,09 a 1,14 |
| E10 | **La EPH no identifica el partido** de los hogares del GBA | Diseño del análisis | Grilla de 31 partidos con precio Zonaprop y peso = hogares inquilinos del Censo (`ref_precios_gba_partido`); 5 partidos sin precio toman el promedio de su corredor | Corredores Norte 32%, Oeste 35%, Sur 33% de los inquilinos del GBA; 0 partidos sin match |

---

## B. Series BCRA, Índice de Salarios y RIPTE

| # | Problema | Evidencia | Decisión | Impacto |
|---|---|---|---|---|
| B1 | **La API publica la UVA con fechas futuras**: el 13-09 ya devuelve valores hasta el 15-10. El campo `ultFechaInformada` de la metadata no coincide con el dato real. | Fase 1 (encuadre) | Filtrar `fecha <= 2026-09-13`, tanto en la descarga como en la limpieza | Se evita usar valores de UVA todavía no vigentes |
| B2 | **Cada serie tiene su frecuencia**: UVA y tipo de cambio diarios; tasas, stock e inflación mensuales | `bcra_cobertura_series` | Todo a grano mensual: UVA a fin de mes y promedio; tasas y tipo de cambio como promedio | Tabla `series_mensuales` con 321 meses |
| B3 | **No hay dólar oficial para 2001**: la serie mayorista del BCRA empieza en mar-2002 | `bcra_cobertura_series` | 2001 = 1 ARS/USD (convertibilidad). Ene-feb 2002 queda sin dato. | Permite medir m² por salario desde 2001 |
| B4 | **El Índice de Salarios total empieza en oct-2016** (12 nulos) | `salarios_cobertura` | Usar el registrado (desde oct-2015) o RIPTE (desde 1994) según la ventana | Stress test H5 posible desde 2016 |
| B5 | **Tasa UVA cercana a 0% en 2023-24**: casi no se otorgaban créditos, así que el promedio es poco representativo | Gráfico en notebook 01 | Marcar el período 2022-24 como de volumen mínimo; no usarlo para inferir precio de mercado | Afecta la lectura de H6 |
| B6 | **Unidad mal rotulada en el destino del crédito** (series 1113-1117): la API dice miles de pesos, pero los valores están en millones | Contraste con el stock total (serie 916) | Renombrar las columnas a `*_millones_ars` y convertir a billones de pesos de ago-26 | `mart_destino_credito` coherente con el stock total |
| B7 | **Dólar Banco Nación diario** y **SIPA con aguinaldo** en junio y diciembre | `stg_dolar_bna`, `stg_sipa` | Dólar: promedio mensual. Sueldo: mediana, y se excluyen junio y diciembre en la comparación de tres lentes | `mart_sueldo_tres_lentes` |
| C1 | **Certificado incompleto en censo.gob.ar** | Descarga | Descargar sin verificar el certificado y **validar el contenido** (firma de archivo Excel) antes de usarlo | 5 cuadros validados |
| OK | **Sin huecos ni fechas duplicadas** en las series mensuales | `bcra_huecos_mensuales` | Sin acción | 0 meses faltantes |

---

## C. Avisos de departamentos en venta (GCBA 2001-2020): el dataset más sucio

**Embudo total:** 580.327 crudos → 449.050 limpios (77,4%). Detalle por año en `gcba_embudo_limpieza` y en `reports/figures/02_gcba_embudo_limpieza.png`.

| # | Problema | Evidencia | Decisión | Filas |
|---|---|---|---|---|
| G1 | **5 esquemas distintos en 20 años**: nombres de columnas, separadores (`;` y `,`) y formatos (CSV y shapefile) | `01_staging` | Cargar por familia de esquema y armonizar en la vista `int_gcba_avisos`. Los shapefiles 2017-19 se leen con DuckDB spatial directo desde el zip | 0 perdidas |
| G2 | **5 líneas corridas en 2007**: 16 campos vacíos al inicio y 30 separadores | `rechazos_gcba` | Rechazar y guardar en `stg_rechazos_gcba`; no se pueden reconstruir porque les falta la calle | 5 |
| R1 | **No son departamentos en venta**: 2015 incluye casas, chalets y un petit hotel; 2019 incluye 25 edificios y 1 alquiler | `gcba_resumen_por_anio` | Excluir | 87 |
| R2 | **Precio o m² inválido**: precio de USD 1, 0 m², 925 m² con precio 0, m² < 15 o > 500 | `gcba_percentiles_m2_usdm2` | Excluir: precio ≤ 0, m² fuera de 15–500 | 3.982 |
| R3 | **Barrio faltante o no reconocible**: 1.378 avisos de 2016 sin geocodificar | `gcba_barrios_variantes` | Excluir si, después de normalizar, no está entre los 48 barrios oficiales | 1.390 |
| R4 | **Duplicados**: 58% en 2017 (snapshots mensuales repetidos), 48% en 2020, 33% en 2016 | `gcba_duplicados_por_anio` | Deduplicar por año, dirección, barrio, m², precio y ambientes | **124.888** |
| R5 | **Outliers de USD/m²**: por ejemplo USD 1/m² en 2008 | `gcba_percentiles_m2_usdm2` | Tukey extremo (k = 3) sobre ln(USD/m²), por año. La escala logarítmica respeta la asimetría de precios y el cálculo por año respeta la inflación en dólares. | 930 |
| G3 | **Mojibake**: "NUÑEZ" escrito de 7 formas (`NU├ÆEZ`, `NUÃ‘EZ`, `NUÔÖ£├ªEZ`…) | `gcba_barrios_variantes` | Normalizar: `LIKE 'NU%EZ'` → NUNEZ | 5.418 avisos recuperados, que se hubieran descartado como barrio inválido |
| G4 | **Barrios truncados o renombrados**: "PARQUE AVELLANED", "VILLA GRAL. MITR" (truncado a 16 caracteres en 2008), MONSERRAT/MONTSERRAT, sub-barrios de 2019-20 (FLORES NORTE/SUR, BARRACAS ESTE/OESTE, VILLA DEVOTO NORTE/SUR) | `gcba_barrios_variantes` | Mapear a los 48 barrios oficiales | 64 variantes → 48 barrios |
| G5 | **Coordenadas**: en 2001 LAT y LON vienen **invertidas** (100% del año); 150 en el Polo Sur (-89,99°) en 2012; 9.167 en (0,0) en 2019 | `gcba_coordenadas_invalidas` | Invertir 2001; poner NULL lo que cae fuera del rectángulo de CABA | Las coordenadas no se usan en el análisis principal |
| G6 | **El USD/m² publicado no cierra** en 2016-2020 (hasta 64,5% de los avisos, en 2016) | `gcba_usd_m2_inconsistente` | **Diagnóstico:** desde 2016 se calcula sobre m² *cubiertos*; antes sobre m² *totales*. Se **recalcula** precio / m² total para todos los años. | Serie comparable 2001-2020 |

**Chequeo cruzado propio:** un error de numeración no determinística (`row_number() OVER ()` sin orden) inflaba los conteos de 4 años en el embudo. Se detectó al comparar contra el perfilado y se corrigió materializando un id estable (`int_gcba_base`).

---

## Tablas limpias resultantes

| Tabla | Grano | Filas | Uso |
|---|---|---|---|
| `hogares_eph` | 1 fila por hogar-trimestre (3 mercados) | 13.175 | Elegibilidad, hipótesis, modelo, segmentación, independientes |
| `series_mensuales` | 1 fila por mes (2000-2026) | 321 | Contexto de mercado, H5, sueldo en tres lentes, m² por salario |
| `avisos_caba` | 1 fila por aviso limpio | 449.050 | USD/m² histórico de CABA |
| `ref_precios_mercado` | 1 fila por mercado | 3 | Precio de referencia USD/m² (Zonaprop Index) |
| `ref_precios_gba_partido` | 1 fila por partido del GBA | 31 | Precio y peso de cada partido (Zonaprop Index + Censo 2022) |
| `stg_censo_hogares` | 1 fila por jurisdicción | 222 | Validación del universo y pesos por partido |

## Limitaciones que se arrastran al análisis

1. **La EPH no mide ahorro ni historial crediticio.** El test de anticipo es un supuesto (≤ 12 ingresos), con sensibilidad.
2. **La EPH capta 2 a 4 puntos menos de inquilinos que el Censo 2022.** Las cantidades absolutas se informan con un rango ajustado.
3. **La no respuesta de ingresos es alta en GBA (41%) y CABA (37%).** `PONDIH` corrige el nivel; la imputación múltiple da una elegibilidad algo menor y se reporta como control de robustez.
4. **Los precios son de publicación, no de escrituración.** Los avisos del GCBA terminan en 2020, así que el precio actual sale del Zonaprop Index. En el GBA se asume la misma distribución de ingresos en todos los partidos.
5. **La tasa promedio del BCRA de 2022-24 no es representativa** por el volumen mínimo de créditos otorgados.
