# Fase 5: Walk-forward CV — Resumen Completado

**Fecha inicio:** 2026-08-15
**Fecha fin:** 2026-08-16
**Estado:** ✅ COMPLETADA

---

## Objetivo

Validar los 3 modelos de Fase 4 con walk-forward CV robusto: 5 folds fijos espaciados (`window_size=365`, horizonte 28 días), misma ventana temporal para los 3 modelos, sin data leakage.

---

## Diseño de folds (`src/evaluation/folds.py`)

5 folds espaciados uniformemente entre el primer punto posible (`MIN(date) + 365`) y el más reciente (`MAX(date) - 27`), calculados dinámicamente desde `sales_long` -- nunca hardcodeados. El fold 5 coincide **exacto** con el smoke test de Fase 4 (verificado bit a bit contra `arima_predictions`/`predictions_lgbm`).

| Fold | TRAIN | VAL |
|---|---|---|
| 1 | 2011-01-29 -> 2012-01-28 | 2012-01-29 -> 2012-02-25 |
| 2 | 2012-02-13 -> 2013-02-11 | 2013-02-12 -> 2013-03-11 |
| 3 | 2013-02-27 -> 2014-02-26 | 2014-02-27 -> 2014-03-26 |
| 4 | 2014-03-14 -> 2015-03-13 | 2015-03-14 -> 2015-04-10 |
| 5 | 2015-03-29 -> 2016-03-27 | 2016-03-28 -> 2016-04-24 |

Tabla de referencia `cv_folds` disponible via `python -m src.evaluation.folds --write`.

---

## Ejecucion por modelo

| Modelo | Script | Scope | Reuso de fold 5 |
|---|---|---|---|
| ARIMA clasico | `src/models/arima_cv.py` | `arima_sample` (32 series) | Re-corrido (gratis, compute local) |
| LightGBM Cuantil | `src/models/lgbm_cv.py` | `lgbm_sample` (~3,000 series) | Re-corrido (gratis, compute local, ~16 min/fold) |
| BQML ARIMA_PLUS | `src/models/bqml_arima_cv.py` | `lgbm_sample` (a diferencia de 4b, que uso las 30,490 completas) | Re-corrido (necesario, cambia de scope) |

**Costo total BQML:** 5 folds x $0.34 = **$1.70** (mas ~$0.37 de la materializacion unica de `sales_long_lgbm_sample`) -- muy por debajo del estimado original de ~$1.80/fold.

---

## Bugs encontrados y corregidos durante Fase 5

1. **`INNER JOIN` en BQML no podaba por muestra -- estimaba ~$104/fold en vez de ~$1.80.** Filtrar `sales_long` contra `lgbm_sample` via `JOIN` en el `WHERE` del `CREATE MODEL` no reduce los bytes escaneados: BigQuery debe leer la columna completa para el rango de fechas de las 30,490 series antes de aplicar el filtro del join, porque ese filtro vive en otra tabla, no en un literal que `CLUSTER BY` pueda usar para podar. **Fix:** materializar `sales_long_lgbm_sample` una sola vez (CREATE TABLE AS SELECT, tarifa normal $6.25/TiB) y entrenar cada fold contra esa tabla ya chica, sin JOIN. Redujo el costo real de ~$104 estimado a $0.34 real por fold.
2. **7 series de BQML con `standard_error` explosivo (p75/p95 en el orden de 1e8-1e44, p50 sano).** Misma familia que las 22 series `NaN` de Fase 4b, pero manifestada como valor finito absurdo -- no aparece como `NULL` y se esconde en el lado `p05`/`p25` porque `GREATEST(valor, 0)` recorta el lado negativo pero no el positivo. Afecta 980 filas de 420,140 (0.23%) en 3 de los 5 folds. **Fix:** columna `bqml_unstable_series` en `cv_pinball_loss` (umbral p75/p95 > 1000, documentado en `diagnose_bqml_outliers.py`) -- visible en el detalle, excluida de las tablas agregadas. Sin fallback silencioso, mismo principio que Fase 4b.
3. **`train_models()` de `lgbm_quantile.py` pisaba modelos entre folds** -- `MODEL_DIR` hardcodeado guardaba siempre en la misma ruta. Fix: parametro `model_dir` opcional, cada fold guarda en `models/lgbm_quantile/fold_{N}/`.

---

## Hallazgo: convergencia de ARIMA cae fuerte en folds tempranos

| Fold | Ventana TRAIN | Convergieron |
|---|---|---|
| 1 | 2011-2012 | 21/32 (66%) |
| 2 | 2012-2013 | 25/32 (78%) |
| 3 | 2013-2014 | 24/32 (75%) |
| 4 | 2014-2015 | 30/32 (94%) |
| 5 | 2015-2016 | 30/32 (94%) |

Los fallos se concentran en `lento`/`muy_lento` y son mucho mas frecuentes en el primer ano de datos -- consistente con "productos nuevos sin historia suficiente" (`skill-m5-evaluation.md`). Insumo directo para el analisis de casos dificiles de Fase 6.

---

## Consolidacion de metricas (`src/evaluation/build_cv_metrics.py`)

Pinball Loss por fila (`cv_pinball_loss`) y agregados (`cv_metrics_by_fold_quantile`, `cv_metrics_by_category`, `cv_metrics_overall`), promediados sobre los 5 folds.

**Comparacion justa -- 32 series de `arima_sample`, presentes en los 3 modelos:**

| Percentil | ARIMA | BQML | LightGBM |
|---|---|---|---|
| p05 | 0.221 | 0.227 | **0.182** |
| p25 | 0.940 | 0.797 | **0.621** |
| p50 | 1.319 | 1.150 | **0.874** |
| p75 | 1.180 | 1.065 | **0.801** |
| p95 | 0.456 | 0.496 | **0.361** |

**BQML vs LightGBM -- scope completo, ~3,000 series de `lgbm_sample`:**

| Percentil | BQML | LightGBM |
|---|---|---|
| p05 | 0.093 | **0.058** |
| p25 | 0.306 | **0.240** |
| p50 | 0.459 | **0.379** |
| p75 | 0.455 | **0.376** |
| p95 | 0.274 | **0.169** |

**LightGBM Cuantil gana en todos los percentiles, en ambos scopes** -- confirma la narrativa esperada (`skill-m5-evaluation.md`). Detalle interesante: BQML supera a ARIMA clasico en p25/p50/p75 pero pierde en las colas (p05/p95) -- coherente con que `ARIMA_PLUS` asume normalidad para sus intervalos, mientras LightGBM Cuantil optimiza cada percentil de forma independiente.

---

## Archivos nuevos/modificados

```
src/evaluation/folds.py              (nuevo)
src/evaluation/cv_io.py              (nuevo)
src/evaluation/metrics.py            (nuevo)
src/evaluation/build_cv_metrics.py   (nuevo)
src/evaluation/diagnose_bqml_outliers.py (nuevo)
src/models/arima_cv.py               (nuevo)
src/models/lgbm_cv.py                (nuevo)
src/models/bqml_arima_cv.py          (nuevo)
src/models/lgbm_quantile.py          (modificado: model_dir parametrizable)
```

**Tablas BigQuery nuevas:** `cv_folds`, `arima_predictions_cv`, `arima_metadata_cv`, `predictions_lgbm_cv`, `bqml_predictions_cv`, `bqml_metadata_cv`, `sales_long_lgbm_sample`, `cv_pinball_loss`, `cv_metrics_by_fold_quantile`, `cv_metrics_by_category`, `cv_metrics_overall`.

---

## Notas

- Test set (ultimos 28 dias reales, `sales_train_evaluation.csv`) sigue bloqueado -- no se toca hasta la evaluacion final.
- `cv_metrics_by_category` esta construida y lista pero aun no revisada a fondo -- punto de partida directo para el desglose por `categoria_zero_rate` de Fase 6.
- El analisis narrativo de casos dificiles (ceros, productos nuevos, eventos) de `skill-m5-evaluation.md` queda pendiente para Fase 6 -- la caida de convergencia de ARIMA en folds tempranos ya es el primer insumo concreto.

---

## Proxima Fase: FASE 6 — Evaluacion

**Estado:** No iniciada (gran parte de la infraestructura de datos ya existe gracias a Fase 5).
