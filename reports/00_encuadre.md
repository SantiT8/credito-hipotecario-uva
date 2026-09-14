# 00 · Encuadre estratégico del problema (pre-análisis)

> **Estado:** validado en el Checkpoint 1 (13-09-2026) y actualizado en el Checkpoint 3 · **Fecha de corte de datos de mercado:** 13-09-2026
>
> **Decisiones del Checkpoint 1:**
> - Escenario base aprobado tal cual está en §5.
> - Test de anticipo: hasta 12 ingresos mensuales, con sensibilidad de 6 y 24.
> - Cobertura geográfica: solo mercados con precio confiable.
>
> **Actualización del Checkpoint 3** (este documento conserva el encuadre original; los cambios se aplican en el análisis):
> - **Gran Rosario queda fuera** por tamaño de muestra. Alcance final: CABA, Partidos del GBA y Gran Córdoba.
> - **El GBA se abre por partido y corredor** (Norte, Oeste, Sur), con pesos de hogares inquilinos del Censo 2022, en lugar de un precio promedio.
> - Los precios se toman de los **reportes oficiales del Zonaprop Index** (CABA y GBA jul-26, Córdoba mar-26), no de notas de prensa.
> - **H1** se muestra como mapa de calor de m²; **H3** pasa a ser descriptiva (composición del hogar); **H6** pasa a contexto; se suma **H7** (trabajos del hogar) como recuadro.
> - **Independientes** (monotributo, autónomos, asalariados que aportan por su cuenta) en un módulo aparte.

---

## 1. Situación

- **El crédito hipotecario volvió, pero se está frenando.**
  - El stock de préstamos hipotecarios a personas pasó de **ARS 6,06 billones (ene-26)** a **ARS 7,10 billones (jun-26)**, según BCRA serie 916 en valores nominales.
  - Los desembolsos de agosto 2026 fueron **USD 242 M**, por debajo del pico de **USD 372 M de octubre 2025** (Infobae, 07-09-2026).
- **Las tasas subieron en 2026.**
  - La tasa promedio de hipotecarios UVA pasó de **5,59%** (ene-26) a **6,91%** (ago-26), según BCRA serie 1240.
  - El 07-09-2026 el Gobierno lanzó un **programa de fondeo con el FGS de ANSES**: 10 licitaciones de $200.000 M, **tasa tope UVA + 7,5%**, primera vivienda, plazo mínimo 15 años y hasta 150.000 UVA.
  - Tasas vigentes por banco (Infobae, 07-09-2026):

    | Banco | TNA sobre UVA | Condición |
    |---|---|---|
    | Banco Nación | 6,7% | |
    | ICBC | 6,9% | |
    | Macro, BBVA, Credicoop, Ciudad, Hipotecario | 7,5% | |
    | Provincia | 9,0% | con cláusula salarial |

- **Precios de publicación** (Zonaprop Index, reportes oficiales; ver `data/reference/zonaprop_precios_2026.csv`):

  | Zona | USD/m² | Reporte |
  |---|---|---|
  | CABA | 2.471 | jul-26 |
  | GBA Norte | 2.410 | jul-26 |
  | GBA Sur | 1.669 | jul-26 |
  | GBA Oeste | 1.575 | jul-26 |
  | Córdoba | 1.474 | mar-26 |

  En el encuadre inicial se usaron valores difundidos por prensa (CABA 2.476, Córdoba 1.443); en el Checkpoint 3 se reemplazaron por los de los reportes originales.

- **Macro:** inflación de 1,7% mensual y 33,5% interanual (ago-26). UVA de $2.116 (13-09-26). Dólar minorista de $1.531,73 (11-09-26).

**Ejemplo ilustrativo del encuadre** (con los datos limpios, los ejemplos por zona están en el documento metodológico, sección 7). Un 2 ambientes en CABA de USD 131.272, financiado al 75%, a UVA + 7,5% y 20 años:

| Concepto | Monto |
|---|---|
| Préstamo | 71.268 UVA |
| **Cuota inicial** | **ARS 1,21 M** |
| **Ingreso neto necesario** (cuota ≤ 25%) | **ARS 4,86 M/mes** |
| **Anticipo + gastos** | **USD 42.000** en efectivo |

El mismo cálculo para un 50 m² en GBA Sur da cuota ARS 0,77 M, ingreso necesario ARS 3,09 M y anticipo + gastos de USD 26.700.

---

## 2. Cliente y rol

- **Cliente (ficticio):** Banco [EMPRESA], un banco privado mediano con red en AMBA y las principales ciudades del interior. Va a participar de las licitaciones del FGS y relanzar su línea hipotecaria UVA en el 4T-2026.
- **Quién pide el análisis:** Gerencia de Productos de Banca Personas, junto con Riesgo Crediticio.
- **Rol del analista:** analista de crédito y negocio.

## 3. Las 3 preguntas pre-análisis (obligatorias)

1. **¿Qué problema de negocio intentamos resolver?**
   - El banco va a recibir fondeo barato con plazo de colocación: **120 días para prestar o hay penalidad**.
   - No sabe cuántos hogares califican realmente, dónde están ni qué los frena.
   - Si diseña mal el producto, no coloca los fondos. Si lo relaja de más, asume riesgo de mora cuando la UVA le gane a los salarios.
2. **¿Qué decisión tiene que tomar el gerente?**
   - **A quién apuntar:** segmento y regiones prioritarias.
   - **Con qué producto:** plazo, % financiado y relación cuota/ingreso máxima.
   - **Qué política de riesgo aplicar:** colchón de cuota/ingreso y cláusulas de protección.
3. **¿Qué es una respuesta satisfactoria?**
   - El **tamaño del mercado elegible hoy**, en hogares, con intervalo de confianza.
   - **Cuál es la barrera principal:** la cuota o el anticipo.
   - **2 o 3 palancas de producto cuantificadas.** Por ejemplo: "pasar de 20 a 30 años suma X mil hogares".
   - **Una alerta de riesgo cuantificada:** cuánto sube la cuota/ingreso en un escenario de desacople UVA vs salarios.
   - Todo cerrado en la frase: *"Recomiendo X porque Y"*.

---

## 4. KPIs

| KPI | Definición operativa | Fuente |
|---|---|---|
| **% de inquilinos elegibles** | Hogares inquilinos cuya cuota inicial es ≤ tope de cuota/ingreso, sobre el total de hogares inquilinos (ponderado con PONDIH) | EPH + supuestos |
| **Mercado elegible** | Cantidad de hogares elegibles expandidos, en miles | EPH |
| **Barrera principal** | % que pasa la cuota pero no el anticipo, vs % que pasa el anticipo pero no la cuota | EPH + supuestos |
| **Impacto de cada palanca** | Δ hogares elegibles al mover un parámetro a la vez: plazo, LTV, tasa, tope de cuota | Simulador |
| **Cuota/ingreso bajo stress** | Relación cuota/ingreso después de 12 y 24 meses repitiendo un episodio histórico de desacople UVA vs salarios | BCRA + INDEC |
| **Contexto del mercado** | Stock real de hipotecarios (ARS constantes) y tasa UVA promedio | BCRA |

---

## 5. Supuestos del producto: escenario base y rangos del simulador

| Parámetro | Base | Rango del simulador | Justificación |
|---|---|---|---|
| Tasa (TNA sobre UVA) | **7,5%** | 4,5% – 10% | Tope del programa FGS. La mayoría de los bancos cotiza en 7,5%. |
| Plazo | **20 años** | 15 – 30 | Oferta típica de 20-25 años. El FGS exige mínimo 15. |
| % financiado (LTV) | **75%** | 60% – 90% | Estándar de mercado. Hipotecario llega a 80%. |
| Tope cuota / ingreso neto | **25%** | 20% – 35% | Criterio usual de los bancos, citado en prensa. |
| Gastos de compra (escritura, sellos, comisión) | **7% del precio** | 5% – 10% | Referencia de mercado. |
| Tope del préstamo | 150.000 UVA | fijo | Condición del FGS. |
| Superficie según tamaño del hogar | 1-2 personas: **45 m²** · 3-4: **60 m²** · 5+: **75 m²** | ±15 m² | Vivienda "adecuada" según la cantidad de miembros. |
| **Test de anticipo** | anticipo + gastos ≤ **12 ingresos mensuales** | 6 – 24 | Equivale a ahorrar 20% del ingreso durante 5 años. La EPH no mide ahorro. |
| Precio USD/m² | Zonaprop Index (CABA, 31 partidos del GBA, Córdoba) | ±20% | Precio de publicación, no de cierre. Ver §7. |
| **Ingreso demostrable** *(Checkpoint 2)* | jefe/a o cónyuge asalariado con aportes | fijo | Los bancos exigen ingresos comprobables. En el Checkpoint 3 se agregó un módulo aparte con monotributistas y autónomos con aportes (EPH `PP05I`, `PP07I`). |
| **Edad máxima al terminar el crédito** *(Checkpoint 2, corregido con fuente)* | edad del jefe/a + plazo ≤ **85 años** | 75 – 85 | Banco Nación: "la edad máxima prevista para la cancelación de las obligaciones de los préstamos será de 85 años inclusive" (iProfesional, 03-12-2025). La propuesta inicial de 75 no tenía respaldo; queda como escenario restrictivo. |

### Embudo de elegibilidad (decisión del Checkpoint 2)

Cada hogar inquilino avanza por los filtros en este orden, y se registra en qué paso queda afuera:

1. **Inquilinos** de los mercados en alcance.
2. **Cuota**: cuota inicial ≤ 25% del ingreso familiar.
3. **Anticipo**: anticipo + gastos ≤ 12 ingresos mensuales.
4. **Ingreso demostrable**: jefe/a o cónyuge asalariado formal.
5. **Edad**: edad del jefe/a + plazo ≤ 85 años (criterio de Banco Nación).

Llegar al final = **elegible**. La **H3** se reformula: la formalidad pasa a ser un filtro, así que el logit analiza qué explica pasar los filtros económicos (cuota + anticipo).

## 6. Hipótesis (con criterio para refutarlas)

| # | Hipótesis | Cómo se testea | Se refuta si... |
|---|---|---|---|
| **H1** | Con las condiciones base, **menos del 20%** de los hogares inquilinos califica por cuota. | % ponderado + IC 95% por bootstrap | El límite inferior del IC supera el 20% |
| **H2** | La barrera que frena es el **anticipo**, no la cuota. | Comparar "pasa cuota y falla anticipo" contra "pasa anticipo y falla cuota" | "Pasa anticipo y falla cuota" es mayor |
| **H3** | La **formalidad laboral** (asalariado con aportes) es el factor que más diferencia la elegibilidad, más que la región o la edad. | Logit ponderado con odds ratios e IC | El OR de formalidad no es el mayor efecto significativo |
| **H4** | La elegibilidad **difiere significativamente entre mercados** y tramos de edad del jefe/a. | Chi-cuadrado ponderado ajustado por efecto de diseño + diferencia en pp | p ≥ 0,05 y diferencia < 5 pp |
| **H5** | En un episodio de desacople como **2018-19**, la cuota/ingreso de un deudor que empezó en 25% **supera el 30%** en 12-24 meses. | UVA (BCRA 31) vs Índice de Salarios (INDEC) en ventanas móviles | El peor episodio histórico no supera el 30% |
| **H6** | La dinámica del stock real de hipotecarios desde 2024 **se mueve en sentido opuesto a la tasa real**. | Series deflactadas y correlación con rezagos (descriptivo, **sin afirmar causalidad**) | Correlación ≈ 0 o del mismo signo |

## 7. Definiciones operativas y alcance

- **Unidad de análisis:** el hogar (base de hogares de la EPH), enriquecido con datos del jefe/a y cónyuge de la base de individuos.
- **Inquilino:** `II7 = 3`. Se analiza también a propietarios y otros regímenes, como control.
- **Ingreso:** `ITF` (ingreso total familiar, **neto y declarado**), ponderado con `PONDIH`, que corrige la no respuesta de ingresos. Los trimestres anteriores se llevan a pesos del último mes con IPC.
- **Formalidad:** jefe/a o cónyuge asalariado (`CAT_OCUP = 3`) con descuento jubilatorio (`PP07H = 1`). Es un proxy de "ingreso demostrable".
- **Período:** los últimos 4 trimestres publicados. *Corrección del Checkpoint 3:* se usan todas las visitas (pool) con ponderadores divididos por 4, en lugar de quedarse con la aparición más reciente de cada hogar, que sobrerrepresentaba a los inquilinos.
- **Cobertura final:**
  - **CABA** (aglomerado 32): precio CABA.
  - **Partidos del GBA** (33): cada hogar se evalúa en los 31 partidos con el precio de cada uno y el peso de sus hogares inquilinos (Censo 2022).
  - **Gran Córdoba** (13): precio de Córdoba.

**Limitaciones que se declaran desde el inicio:**
- La EPH no mide ahorro, historial crediticio ni deudas: el test de anticipo es un supuesto.
- Los precios son de publicación, no de escrituración (suelen estar entre 5% y 10% por encima).
- La EPH es urbana (31 aglomerados) y el ingreso es declarado, con subdeclaración conocida en deciles altos.
- Es un ejercicio de dimensionamiento, no un scoring individual.

---

## 8. Fuentes

- **INDEC, EPH:** bases usuarias de hogares e individuos. [Bases de datos INDEC](https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos)
- **BCRA, API de Estadísticas v4.0:** series 31 (UVA), 1240 (tasa hipotecaria UVA), 1217 (tasa fija), 916 (stock de hipotecarios a personas humanas), 27/28 (inflación), 4 (tipo de cambio minorista).
- **INDEC, Índice de Salarios:** vía API de Series de Tiempo de datos.gob.ar (`149.1_TL_INDIIOS_OCTU_0_21`).
- **GCBA, Departamentos en venta 2001-2020:** data.buenosaires.gob.ar (CC-BY 2.5 AR).
- **INDEC, Censo 2022:** hogares por régimen de tenencia (cuadros 6).
- **datos.gob.ar:** RIPTE, remuneraciones del SIPA y dólar Banco Nación vendedor.
- **Zonaprop Index:** reportes oficiales CABA y GBA (jul-26) y Córdoba (mar-26).
- **Referencias de supuestos (condiciones de crédito y programa FGS):** Infobae (07-09-2026), iProfesional (03-12-2025).

## 9. Nota de calidad detectada en el encuadre

- La API del BCRA publica la **UVA con fechas futuras**: el 13-09-26 ya devuelve valores hasta el 15-10-26, porque la UVA se calcula con CER anticipado.
- Además, el campo de metadata `ultFechaInformada` no coincide con el último dato real.
- Decisión: filtrar `fecha <= fecha de corte`. Queda registrado en `01_calidad_datos.md`.
