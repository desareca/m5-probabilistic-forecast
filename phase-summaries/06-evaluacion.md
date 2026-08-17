# Fase 6: Evaluación — Resumen Completado

**Fecha inicio:** 2026-08-16
**Fecha fin:** 2026-08-17
**Estado:** ✅ COMPLETADA

---

## Objetivo

Comparativa honesta entre ARIMA clásico, BQML ARIMA_PLUS y LightGBM Cuantil sobre los
resultados de walk-forward CV (Fase 5): Pinball Loss por percentil, por categoría real
(FOODS/HOBBIES/HOUSEHOLD), y análisis narrativo de los tres casos difíciles pedidos en
`INSTRUCCIONES.md` — series con alta tasa de ceros, productos nuevos sin historia,
semanas con eventos especiales.

---

## Infraestructura construida

| Script/Notebook | Contenido |
|---|---|
| `src/evaluation/build_cv_metrics.py` (Fase 5, reutilizado) | `cv_pinball_loss`, `cv_metrics_by_fold_quantile`, `cv_metrics_by_category` (zero-rate), `cv_metrics_overall` |
| `src/evaluation/build_case_analysis.py` (nuevo) | `cv_metrics_by_product_category`, `series_release_dates` + `cv_metrics_by_release_age`, `cv_metrics_by_event` |
| `notebooks/02_evaluation.ipynb` (nuevo) | Notebook ejecutable con las 5 secciones: comparativa general, categoría real, 3 casos difíciles, convergencia ARIMA, conclusiones |

---

## Lección de diseño: el split de dos alcances es obligatorio en cualquier desglose que incluya ARIMA

La primera versión de `build_case_analysis.py` no separaba por `in_arima_sample` y produjo
un resultado contraintuitivo: ARIMA "ganando" en la categoría HOBBIES (0.167 vs. 0.306 de
BQML). La causa real: ARIMA solo tiene predicciones para las 32 series de `arima_sample`,
mientras que BQML/LightGBM en esas tablas promediaban sobre las ~3,000 series de
`lgbm_sample` completo — comparar la fila `arima` contra un promedio de una población ~100x
más grande no es una comparación válida.

**Fix:** todo desglose que incluya ARIMA reporta dos alcances por separado (mismo patrón que
`cv_metrics_overall` de Fase 5):
- **Comparación justa** — 32 series de `arima_sample`, los 3 modelos.
- **BQML vs. LightGBM, alcance completo** — ~3,000 series de `lgbm_sample`.

Esto corrigió el resultado de HOBBIES (LightGBM gana en ambos alcances, como era de
esperar) y se aplicó de forma consistente a los 4 desgloses de este documento.

---

## Resultados

### Comparativa general (reconfirma Fase 5)

LightGBM Cuantil gana en los 5 percentiles, en ambos alcances. BQML supera a ARIMA en el
cuerpo de la distribución (P25–P75) pero pierde en las colas (P05/P95) — coherente con que
`ARIMA_PLUS` deriva sus intervalos asumiendo normalidad, mientras LightGBM optimiza cada
percentil de forma independiente.

### Por categoría real (FOODS/HOBBIES/HOUSEHOLD)

**Comparación justa (32 series, P50):**

| Categoría | ARIMA | BQML | LightGBM |
|---|---|---|---|
| FOODS | 1.994 | 1.796 | **1.337** |
| HOBBIES | 0.167 | 0.114 | **0.097** |
| HOUSEHOLD | 0.674 | 0.594 | **0.483** |

**BQML vs. LightGBM, alcance completo (P50):**

| Categoría | BQML | LightGBM | n_obs |
|---|---|---|---|
| FOODS | 0.640 | **0.517** | 391,328 |
| HOBBIES | 0.306 | **0.270** | 156,464 |
| HOUSEHOLD | 0.297 | **0.253** | 292,292 |

LightGBM gana en las 3 categorías, en ambos alcances — sin cambios de ranking respecto a la
comparativa general. FOODS muestra el error absoluto más alto en los 3 modelos; probablemente
refleja el mayor volumen de venta promedio de esa categoría, no necesariamente que sea "más
difícil" de predecir (ver limitación metodológica abajo).

### Series con alta tasa de ceros

**Comparación justa (32 series, P50):**

| Bucket | ARIMA | BQML | LightGBM |
|---|---|---|---|
| rapido | 3.118 | 3.267 | **2.351** |
| medio | 0.978 | 0.979 | **0.821** |
| lento | 0.334 | 0.266 | **0.242** |
| muy_lento | 0.154 | 0.087 | **0.082** |

**BQML vs. LightGBM, alcance completo (P50):**

| Bucket | BQML | LightGBM | n_obs |
|---|---|---|---|
| rapido | 2.004 | **1.633** | 29,680 |
| medio | 1.022 | **0.839** | 151,452 |
| lento | 0.400 | **0.334** | 334,264 |
| muy_lento | 0.115 | **0.097** | 324,688 |

LightGBM gana en los 4 buckets en ambos alcances (única excepción: BQML pierde contra ARIMA
en `rapido` dentro del alcance justo — 3.267 vs. 3.118 — probablemente ruido de muestra
pequeña). **Hipótesis inicial no confirmada:** la ventaja relativa de LightGBM sobre BQML es
uniforme (~16–19%) en los 4 buckets, sin amplificarse en `muy_lento` como se esperaba.

### Productos nuevos sin historia

`release_date` = primera semana con precio registrado en `sell_prices` (definición oficial
M5). `nuevo_lt_90d` = predicción dentro de los primeros 90 días desde el release.

**Alcance completo (P50, el representativo):**

| Bucket | BQML | LightGBM | n_obs |
|---|---|---|---|
| nuevo_lt_90d | 0.587 | **0.481** | 21,562 |
| establecido | 0.541 | **0.447** | 689,248 |

`nuevo_lt_90d` SÍ tiene mayor Pinball Loss que `establecido` (BQML +9%, LightGBM +8%) —
confirma que los productos recién lanzados son más difíciles de predecir. El efecto es
moderado y **no se amplifica para LightGBM** frente a BQML (ventaja relativa casi idéntica en
ambos buckets). En el alcance justo (32 series) el patrón se invierte, probablemente por
tamaño de muestra insuficiente de productos nuevos dentro de esas 32 series.

Insumo relacionado (Fase 5): convergencia de ARIMA por fold — 66% → 78% → 75% → 94% → 94%,
folds ordenados de más antiguo a más reciente. Mide un fenómeno relacionado pero distinto
(ventana de entrenamiento corta al inicio del dataset completo, no la antigüedad de un
producto individual).

### Semanas con eventos especiales — hallazgo de diseño real

Ninguna de las 5 ventanas VAL del walk-forward CV (Fase 5) cae en diciembre — los 5 folds
caen entre enero y abril. **Navidad — el caso extremo de cierre de tienda documentado en el
EDA y modelado explícitamente como feature (`is_christmas`) — nunca se valida en este
esquema de CV.** El bucket `navidad` no tiene ninguna observación (`n_obs = NULL`).

Adicionalmente, y de forma contraintuitiva, los días con evento (no-navidad, ej.
SuperBowl/Valentine/Easter) muestran Pinball Loss *menor* que los días sin evento, en los 3
modelos y ambos alcances — posible explicación: los eventos capturados en el rango ene–abr
tienen efectos moderados y algo predecibles frente a la variabilidad general del resto del
año.

---

## Limitación metodológica a documentar en Fase 10

Esta comparación responde bien "¿qué modelo es mejor en cada segmento?" (LightGBM, de forma
consistente) pero no "¿qué segmento es intrínsecamente más difícil de predecir?", porque la
Pinball Loss implementada (`src/evaluation/metrics.py`) no está escalada por el nivel de venta
de la serie — a diferencia de la *Weighted Scaled Pinball Loss* oficial de M5 mencionada en
`INSTRUCCIONES.md`. Comparar magnitudes absolutas entre categorías/segmentos de distinta
escala de venta (ej. FOODS vs. HOBBIES, `rapido` vs. `muy_lento`) no es directamente válido
para juzgar "dificultad" — sólo para comparar modelos dentro del mismo segmento.

El walk-forward CV de Fase 5, al espaciar folds uniformemente sin garantizar cobertura
estacional completa, nunca prueba el caso Navidad — la afirmación "el modelo maneja bien los
casos extremos como Navidad" no está respaldada por este CV específico, aunque sí por el
feature engineering de Fase 3.

---

## Narrativa final del proyecto

ARIMA establece el piso estadístico, BQML escala eso a producción pero mantiene las
limitaciones de distribución normal en las colas, LightGBM Cuantil supera a ambos de forma
consistente en todos los segmentos analizados (percentil, categoría, tasa de ceros,
antigüedad de release). La ventaja de LightGBM es notablemente estable (~15–20%) en vez de
concentrarse en los casos "difíciles" esperados — es una historia más matizada y honesta que
la versión simplificada ("LightGBM brilla especialmente en demanda intermitente/productos
nuevos"): LightGBM gana de forma consistente y pareja, no solo en los extremos.

---

## Archivos nuevos/modificados

```
src/evaluation/build_case_analysis.py   (nuevo)
notebooks/02_evaluation.ipynb            (nuevo, ejecutado)
README.md                                (actualizado: estado Fase 6, estructura repo)
```

**Tablas BigQuery nuevas:** `cv_metrics_by_product_category`, `series_release_dates`,
`cv_metrics_by_release_age`, `cv_metrics_by_event`.

---

## Próxima Fase: FASE 7 — MLOps

**Estado:** No iniciada. Mayor incertidumbre de timeline del proyecto (Docker, Vertex AI
Pipelines/KFP, Model Registry).
