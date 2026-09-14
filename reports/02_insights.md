# 02 · Hallazgos: qué pasa, por qué importa y qué evidencia lo respalda

> **Estado:** versión final, con las correcciones y decisiones del Checkpoint 3.
>
> **Fuente única de cifras:** `data/processed/resultados/kpis.json`, generado por `src/export_results.py`. Este archivo se genera con `src/build_docs.py`.
>
> **Notebooks:** `03_analisis_hipotesis.ipynb`, `04_modelo_segmentacion_simulador.ipynb`, `05_independientes.ipynb`.
>
> **Escenario base:** UVA + 7,5% · 20 años · 75% financiado · cuota hasta 25% del ingreso · anticipo + gastos hasta 12 ingresos · ingreso demostrable · edad al terminar hasta 85 años. UVA $ 2.116,04 · dólar minorista $ 1.531,73 · Zonaprop Index.

---

## Resumen en una frase

**Hoy 1 de cada 8 hogares inquilinos (155 mil de 1,2 millones) podría tomar un hipotecario UVA.** El freno es el efectivo inicial frente al precio. **Un producto a 30 años con 80% financiado lleva ese número a 201 mil (+30%) sin subir el tope de cuota, y una línea para independientes con aportes lo lleva a 259 mil.**

---

## Hallazgo 1 · El mercado elegible: 155 mil hogares (12,4%)

- **Qué pasa.** Hogares que superan cada filtro, sobre 1,2 millones de hogares inquilinos en CABA, Partidos del GBA y Gran Córdoba:

  | Filtro | Hogares | % del total |
  |---|---|---|
  | Inquilinos | 1,2 millones | 100,0% |
  | Pagan la cuota | 275 mil | 22,1% |
  | Juntan el anticipo | 220 mil | 17,7% |
  | Ingreso demostrable | 156 mil | 12,6% |
  | Cumplen la edad | 155 mil | 12,4% |

- **Por qué importa.** El mercado "listo" es de 155 mil hogares (IC 95% 10,4%–14,3%; ajustado al Censo, entre 169 mil y 176 mil). Si la campaña apunta a todos los inquilinos, la mayoría de las solicitudes van a ser rechazadas.
- **H1 · En el límite:** el 22,1% paga la cuota (IC 19,6%–24,5%).
- **Evidencia.** Figura `03_embudo_elegibilidad`; `embudo_total.csv`; `embudo_por_zona.csv`.

## Hallazgo 2 · La superficie cambia todo (H1 como mapa de calor)

- **Qué pasa.** Si todos buscaran 45 m², calificaría el 18,1%; con 60 m², el 9,3%; con 75 m², el 5,0%. En CABA pasa de 17,8% a 4,4%; en GBA Oeste, de 21,6% a 6,8%.
- **Por qué importa.** Viviendas más chicas o usadas son una palanca comercial directa.
- **Evidencia.** Figuras `03_calor_m2_zona` y `03_calor_m2_integrantes`; `h1_calor_zona.csv`.

## Hallazgo 3 · El freno es el efectivo inicial

- **Qué pasa.** Un hogar califica si la vivienda cuesta hasta 37,5 ingresos mensuales (anticipo) o 41,4 (cuota). La vivienda de referencia del hogar típico cuesta 72 ingresos. El 78% no alcanza ninguno de los dos límites.
- **Por qué importa.** Bajar la tasa o subir el tope de cuota, por separado, no suma hogares. **H2 confirmada con matiz.** % financiado de equilibrio: 77%.
- **Evidencia.** Figura `03_precio_en_ingresos`; `kpis.json → h2`.

## Hallazgo 4 · ¿Qué pasa si…? Lo que suma y lo que resta

| Medida | Hogares |
|---|---|
| ¿Y si se compra una vivienda 20% más barata (usada o más chica)? | +86 mil |
| ¿Y si acepta monotributistas y autónomos con aportes? | +46 mil |
| ¿Y si hace las dos cosas: 30 años y 80%? | +46 mil |
| ¿Y si un plan de ahorro permite juntar 24 meses de ingreso? | +39 mil |
| ¿Y si financia el 80% en vez del 75%? | +13 mil |
| ¿Y si la tasa baja de 7,5% a 5,5%? | 0 |
| ¿Y si acepta cuotas de hasta 30% del ingreso? | 0 |
| ¿Y si el banco presta a 30 años en vez de 20? | −18 mil |

| Riesgo | Hogares |
|---|---|
| Si el anticipo hay que juntarlo en 6 meses de ingreso | −136 mil |
| Si los precios suben 20% | −53 mil |
| Si el banco exige cuota de hasta 20% del ingreso | −41 mil |
| Si la tasa sube a 9,5% | −18 mil |
| Si la edad máxima al terminar de pagar baja a 75 | −18 mil |

- **Evidencia.** Figuras `04_que_pasa_si`, `04_que_lo_empeora`, `04_grilla_plazo_ltv`, `04_escenarios_producto`.

## Hallazgo 5 · Composición del hogar (H3, descriptiva)

- Parejas con hijos: 39% de los inquilinos, 12,6% elegible.
- Parejas sin hijos: 32,9% elegible (dos ingresos, mayor ingreso por persona).
- Hogares de un solo adulto: unipersonales 5,8%, monoparentales 4,6%.
- En las parejas, la elegibilidad es similar según quién figura como jefe/a. Las diferencias aparecen en hogares de un solo adulto, con menor ingreso por persona cuando encabeza una mujer. El modelo logístico (AUC 0,78) muestra asociaciones, no causas: estudios superiores ×3,1, dos o más perceptores ×2,4, pareja sin hijos ×2,5.
- **Evidencia.** Figuras `03_perfil_hogares`, `04_logit_odds`; `h3_perfil_hogares.csv`.

## Hallazgo 6 · Dónde y a qué edad (H4, parcialmente confirmada)

| Zona | % elegible | Hogares elegibles |
|---|---|---|
| GBA Oeste | 16,4% (IC 13,1–20,3) | 36 mil |
| Gran Córdoba | 15,8% (IC 12,4–19,3) | 29 mil |
| GBA Sur | 11,7% (IC 8,9–14,8) | 24 mil |
| CABA | 10,8% (IC 7,5–14,3) | 47 mil |
| GBA Norte | 9,4% (IC 7,3–11,6) | 19 mil |

- Diferencia entre mercados no concluyente (p = 0,37); por edad sí (p = 0,03). Los corredores son los mismos hogares del GBA con los precios de cada corredor.
- **Evidencia.** Figura `03_elegibles_por_zona_edad`; `h4_zona.csv`, `h4_edad.csv`.

## Hallazgo 7 · Independientes: 47 mil hogares pueden pagar sin recibo de sueldo

- 251 mil hogares inquilinos tienen jefe/a o cónyuge independiente con aportes; en 174 mil no hay asalariado con aportes en la pareja; 47 mil pagan la cuota y juntan el anticipo (ingreso mediano $ 5,7 millones).
- Su ingreso varía más entre trimestres: cambio típico 31% contra 23% de los asalariados con aportes.
- **Evidencia.** Notebook 05; figuras `05_independientes_embudo`, `05_volatilidad_ingresos`.

## Hallazgo 8 · Riesgo: la cuota puede pasar a un tercio del ingreso (H5, confirmada)

- Un crédito de sep-2023 con cuota al 25% llegó al 32,9% a los 24 meses. El 11% de las ventanas de 24 meses desde 2016 superó el 30%.
- El sueldo mediano registrado equivale a USD 1.132 (cerca de 2017 en dólares), pero en poder de compra vale $ 1,7 millones contra $ 2,1 millones en 2017.
- **Evidencia.** Figuras `03_stress_uva_salarios`, `03_sueldo_tres_lentes`.

## Recuadro · posible punto de fuga (H7)

- Donde trabajan dos o más personas califica el 21,0%; con una persona y un trabajo, el 5,3%. Una persona con dos empleos pasa cuota y anticipo en el 17,8% de los casos, pero solo el 48% tiene ingreso demostrable.

## Hallazgo 9 · 351 mil hogares cerca de calificar

| Perfil | Hogares | Edad | Con aportes | Dos ingresos | Cubren del ingreso necesario |
|---|---|---|---|---|---|
| Dos ingresos, a un paso de calificar | 175 mil | 43 | 73% | 95% | 79% |
| Un ingreso, hogares jóvenes | 152 mil | 35 | 54% | 34% | 78% |
| Pueden pagar, pero sin recibo de sueldo | 24 mil | 39 | 0% | 55% | 180% |

- Segmentación exploratoria (silhouette 0,22): guía comercial, no grupos rígidos.

## Hallazgo 10 · El cuello de botella está en el fondeo

- Préstamo medio con el producto propuesto: $ 121,6 millones. El programa ($ 2 billones) financia ~16 mil créditos, frente a 201 mil hogares elegibles (12 veces más).

## Robustez

- Imputación de la no respuesta: 11,1% (IC 9,7–12,6); error de validación 1,7 puntos.
- Subdeclaración corregida con el SIPA: 14,6% (mediana) a 16,8% (promedio).
- Censo 2022: cantidades absolutas entre 169 mil y 176 mil.

## Contexto de mercado

- Stock real de hipotecarios: 7,4 billones de pesos de ago-26, el 52% del pico de may-18. Tasa UVA promedio: 6,91%.
- En jun-26, el 58% del saldo financia compra de vivienda.