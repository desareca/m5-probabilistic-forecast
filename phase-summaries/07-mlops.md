# Fase 7: MLOps — Resumen Completado

**Fecha inicio:** 2026-08-29
**Fecha fin:** 2026-08-30
**Estado:** ✅ COMPLETADA

---

## Objetivo

Pipeline reproducible y modelo registrado en Vertex AI: Docker + Artifact Registry,
Custom Training Job + Model Registry, Vertex AI Pipeline (KFP) con lógica condicional
de registro, Batch Prediction sobre el test set real, y Cloud Scheduler para
reentrenamiento periódico.

---

## Tarea 1 — Docker + Artifact Registry

`Dockerfile` + `requirements-training.txt` (subset minimalista de dependencias, sin
Jupyter/TensorFlow/kfp) + `terraform/artifact_registry.tf`. Imagen final:
`us-central1-docker.pkg.dev/mle-m5-forecast/m5-training/lgbm-quantile` — llegó a `v5`
tras varias iteraciones de bugs reales (ver más abajo).

Build/push vía **Cloud Build** (`gcloud builds submit`), no `docker build && docker push`
local: Cloud Shell tuvo fallos sistemáticos de red (`connection refused`) al hacer push
directo a Artifact Registry.

## Tarea 2 — Custom Training Job + Model Registry

`pipelines/training_job.py` (script parametrizado, reutiliza `src/models/lgbm_quantile.py`)
+ `pipelines/submit_training_job.py` (lanza `aiplatform.CustomJob`, lee `metrics.json` desde
GCS, registra en Model Registry con Pinball Loss por percentil como labels).

Modelo registrado: `projects/646167436505/locations/us-central1/models/7276418968796004352`
(run `20260829-230231`, Pinball Loss avg = 0.2786, ventana = fold 5 del walk-forward CV).

**Caveat documentado:** `Model.upload()` exige `serving_container_image_uri` — no existe
container prebuilt de Vertex AI para LightGBM, así que apunta a la misma imagen de
training. Esto satisface el campo obligatorio pero **no es deployable de verdad** (no
implementa el contrato HTTP de predicción de Vertex AI) — determinó el diseño de la Tarea 4.

## Tarea 3 — Vertex AI Pipeline (KFP)

`pipelines/m5_pipeline.py` (5 componentes: `ingest_check` → `build_features` → `train` →
`evaluate` → `register` condicional) + `pipelines/compile_pipeline.py` +
`pipelines/run_pipeline.py`.

Corrida completa verificada: `ingest-check`/`build-features`/`train`/`evaluate` en verde,
`registrar-si-mejora` correctamente **no disparado** (el run no mejoró el baseline de
0.2444) — confirma que la lógica condicional funciona, no solo que el pipeline "corre".

## Tarea 4 — Batch Prediction sobre el test set real

El verdadero test set de M5 (`sales_train_evaluation.csv`, 28 días más allá de
`sales_long`) nunca se había cargado a BigQuery — bloqueado a propósito desde la Fase 2
(ver `phase-summaries/02-datos-eda.md`). Esta tarea lo desbloquea, la única vez en todo
el proyecto:

1. `src/data/build_sales_test_true.py` — carga el CSV (ya en GCS desde Fase 2, no hace
   falta Kaggle de nuevo) y reshape wide→long solo de los días incrementales →
   `test_labels` (853,720 filas = 28 × 30,490).
2. `src/features/build_features_test.py` — reutiliza `sql/build_features_train.sql` vía
   sustitución de texto con anclas verificadas (`assert count==1`), extendiendo la fuente
   a `sales_long UNION ALL test_labels` → `features_test`.
3. `pipelines/batch_predict.py` — carga los `.txt` de LightGBM directo desde GCS (no
   Batch Prediction Job nativo de Vertex AI, por el caveat de la Tarea 2) y predice
   localmente (853K filas, solo inferencia — no justifica un CustomJob nuevo) →
   `predictions_test` + `test_evaluation_metrics`.

### Resultado — Pinball Loss sobre test set real (nunca visto hasta ahora)

| Percentil | Test real | CV baseline (5-fold, Fase 5) |
|---|---|---|
| P05 | 0.071 | 0.058 |
| P25 | 0.290 | 0.240 |
| P50 | 0.458 | 0.379 |
| P75 | 0.453 | 0.376 |
| P95 | 0.199 | 0.169 |
| **avg** | **0.294** | **0.244** |

**El Pinball Loss real es ~20% más alto que la estimación de walk-forward CV en todos
los percentiles, de forma consistente.** No es un resultado que se pueda maquillar:
el CV fue optimista respecto al verdadero futuro no visto. Hipótesis más probable: el
CV promedia 5 folds distribuidos a lo largo de 2011-2016, mientras que el test real es
un único período (abril-mayo 2016) — un solo punto no tiene el efecto promediador de
5 folds, y puede coincidir con dinámica de mercado (precios, eventos) distinta a la
mezcla histórica que vio el CV. Vale la pena mencionar esto explícitamente en la Fase 10
como ejemplo de honestidad metodológica: la comparación de modelos (LightGBM > BQML >
ARIMA) sigue siendo válida, pero la magnitud absoluta de error en producción sería más
alta que lo que el CV sugiere.

## Tarea 5 — Cloud Scheduler

`terraform/scheduler.tf` — Cloud Scheduler → REST API de Vertex AI Pipelines directo (sin
Cloud Function intermedia). **Creado pausado a propósito**: el dataset M5 es estático
(`sales_long`/`features_train` nunca cambian, `build_features` es idempotente desde la
Tarea 3), así que una cadencia mensual entrenaría siempre sobre los mismos datos sin
señal real de "datos nuevos". Se implementó para demostrar la capacidad técnica
(Scheduler → Pipelines vía REST, con el permiso `serviceAccountTokenCreator` que
requiere) sin gastar cómputo en reentrenamientos sin valor. En un escenario real con
datos vivos, el trigger correcto sería llegada de datos nuevos o drift de métricas
en producción — no un cron ciego.

**No probado en ejecución real** (decisión consciente: correrlo cuesta lo mismo que
cualquier pipeline run, y ya se verificó esa lógica en la Tarea 3) — el payload REST
(`templateUri`/`runtimeConfig.parameterValues`) es la parte con más incertidumbre si en
algún momento se activa.

---

## Bugs reales encontrados y corregidos

1. **Import transitivo pesado:** `lgbm_quantile.py` importaba constantes desde
   `arima_baseline.py`, arrastrando `pmdarima`/`statsmodels` (no instalados en el
   container) → `ModuleNotFoundError`. Fix: `src/common.py` con las piezas livianas
   compartidas.
2. **ENTRYPOINT del Dockerfile** corría el script suelto (`python pipelines/training_job.py`)
   en vez de como módulo → `ModuleNotFoundError: No module named 'src'` (solo
   `/app/pipelines` quedaba en `sys.path`, no `/app`).
3. **`libgomp.so.1` faltante** — `python:3.10-slim` no trae el runtime de OpenMP que el
   binario compilado de LightGBM necesita.
4. **Permiso IAM "actAs" faltante** (dos veces, mismo patrón): `mle-m5-sa` necesitó
   `roles/iam.serviceAccountUser` sobre sí misma para lanzar CustomJobs, y el agente de
   servicio de Cloud Scheduler necesitó `roles/iam.serviceAccountTokenCreator` sobre
   `mle-m5-sa` para el `oauth_token` del `http_target`.
5. **`Model.upload()` exige `serving_container_image_uri`** — no hay opción de registro
   "solo artefacto" en el SDK instalado.
6. **`mirror.gcr.io` rechazado por Vertex AI** como "Invalid image URI" — Custom Jobs
   solo aceptan Artifact Registry/GCR/Docker Hub, no espejos arbitrarios.
7. **Componentes KFP con imagen pública + `pip install` en runtime fallaban con exit
   code 1 y CERO logs de contenedor** — mismo patrón de red saliente poco confiable que
   el bug de Cloud Build. Fix real: reutilizar la propia imagen de Artifact Registry
   (sin `packages_to_install`, sin dependencia de red externa en runtime) para los 4
   componentes livianos del pipeline.
8. **`load_csv_to_bigquery()` sin `write_disposition` explícito** — el default de
   BigQuery para load jobs es `WRITE_APPEND`, no reemplazar. Correr el script de ingesta
   dos veces duplicó `sales_evaluation_wide` exactamente 2x. Fix: `WRITE_TRUNCATE`
   explícito, aplicable retroactivamente a cualquier futura carga con este helper.
9. **`JSON_EXTRACT_SCALAR` con path no constante** — el patrón de `CROSS JOIN` con una
   tabla de días (usado en `sql/reshape_wide_to_long.sql`, tal como está en el repo)
   nunca corrió realmente así: BigQuery exige que el segundo argumento sea una expresión
   constante. El reshape real de Fase 2 usó el patrón `UNION ALL` de
   `sql/reshape_wide_to_long.py` (un `SELECT` literal por columna) — replicado
   correctamente en `build_sales_test_true.py`.

---

## Archivos nuevos

```
Dockerfile
.dockerignore
requirements-training.txt
src/common.py
pipelines/training_job.py
pipelines/submit_training_job.py
pipelines/m5_pipeline.py
pipelines/compile_pipeline.py
pipelines/run_pipeline.py
pipelines/batch_predict.py
src/data/build_sales_test_true.py
src/features/build_features_test.py
terraform/artifact_registry.tf
terraform/iam_vertex.tf
terraform/scheduler.tf
```

**Tablas BigQuery nuevas:** `test_labels`, `features_test`, `predictions_test`,
`test_evaluation_metrics`, `sales_evaluation_wide`.

**Modificados:** `src/models/arima_baseline.py` (re-exporta desde `common`),
`src/models/lgbm_quantile.py` (importa de `common`), `src/data/load_to_bq.py`
(`WRITE_TRUNCATE`), `terraform/outputs.tf`.

---

## Próxima Fase: FASE 8 — Tablas agregadas

**Objetivo:** Tablas livianas en BigQuery optimizadas para Looker Studio
(`agg_predictions`, `agg_metrics`, `agg_weekly_comparison`). Trabajo de SQL puro —
no requiere la Workstation (Cloud Shell alcanza, sin la memoria extra que
Fase 4c/5 necesitaron para entrenar LightGBM).
