# Fase 4: Modelos — Resumen Completado

**Fecha inicio:** 2026-07-26
**Fecha fin:** 2026-07-26
**Estado:** ✅ COMPLETADA

---

## Objetivo

Entrenar los 3 modelos baseline/challenger del proyecto sobre un smoke test de un solo fold (TRAIN = 365 días inmediatamente antes de VAL, VAL = últimos 28 días de `sales_long`) — el mismo esquema temporal que reutilizará Fase 5 en cada fold del walk-forward completo.

---

## 4a — ARIMA Clásico (`src/models/arima_baseline.py`)

- **Muestra:** 32 series de `m5_dataset.arima_sample` (8 por categoría de `categoria_zero_rate`: rápido/medio/lento/muy_lento, estratificada — no proporcional)
- **Ajuste:** `pmdarima.auto_arima` por serie individual, `seasonal=False`, `max_p=5`/`max_q=5`/`max_d=2`, `maxiter=200`
- **Cuantiles:** derivados de forecast + error estándar por horizonte, asumiendo normalidad (`scipy.stats.norm.ppf`), `clip(0, None)`
- **Resultado:** **30/32 series convergieron** (2 fallos genuinos, uno en `medio` y uno en `muy_lento`, persistentes incluso tras subir `maxiter` — no artefacto del optimizador)
- **Tablas generadas:** `arima_predictions`, `arima_metadata`

---

## 4b — BQML ARIMA_PLUS (`sql/train_bqml_arima.sql`, `sql/predict_bqml_arima.sql`)

- **Escala:** las 30,490 series completas de `sales_long`, entrenadas 100% en BigQuery SQL
- **Config:** `holiday_region = 'US'`, `auto_arima_max_order = 4`
- **Costo real:** **$18.27** (59.88 GB facturados a la tarifa de modelos de series de tiempo) — por encima del estimado de $15.94 en INSTRUCCIONES.md, pero dentro de rango razonable
- **Tiempo:** 4 min 42 s
- **Resultado:** **30,490/30,490 series con modelo válido**. Hallazgo: **22 series (0.07%) con `standard_error = NaN`** (20 `muy_lento`, 2 `lento` extremo) — documentado explícitamente en `bqml_metadata`, sin fallback silencioso
- **Comparación de tasa de fallo:** 0.17% dentro de `muy_lento` en BQML vs. 12.5% (1/8) en ARIMA clásico dentro de la misma categoría — el pipeline más completo de ARIMA_PLUS (STL, holiday effects) maneja intermitencia notablemente mejor que ARIMA "desnudo"
- **Cuantiles:** derivados de `forecast_value` + `standard_error` de `ML.FORECAST`, mismo criterio de normalidad que 4a (z-scores hardcodeados, BigQuery no tiene `norm.ppf` nativo)
- **Tablas generadas:** `bqml_predictions`, `bqml_metadata`

---

## 4c — LightGBM Cuantil (`src/models/lgbm_quantile.py`)

- **Muestra:** `m5_dataset.lgbm_sample` (~3,000 series, muestra **proporcional** a la distribución real — no las 30,490 completas, por inviabilidad de tiempo/memoria pensando ya en los 5 folds de Fase 5)
- **Modelos:** 5 independientes (uno por percentil P5/P25/P50/P75/P95), `objective='quantile'`, hiperparámetros fijos (`n_estimators=1000`, `learning_rate=0.05`, `num_leaves=127`), sin early stopping
- **Categóricas:** cast a `category` dtype (`day_of_week`, `day_of_month`, `month`, `week_of_year`, `event_type`, `is_event`, `is_christmas`, `snap_active`, `price_changed`)
- **Quantile crossing:** `np.sort` sobre las 5 columnas por fila — **0 violaciones de monotonicidad, 0 negativos, 0 nulls** en la validación posterior
- **Tiempo:** ~16 min de entrenamiento total (5 modelos)
- **Tabla generada:** `predictions_lgbm`

---

## Decisión de Infraestructura

**Workstation subida de `e2-standard-4` (16 GB) a `e2-highmem-4` (32 GB)** tras OOM recurrente durante el entrenamiento de 4c — la carga de ~11.1M filas × ~50 columnas (antes de acotar a `lgbm_sample`) excedía la RAM disponible incluso después de varias rondas de optimización de memoria (dtypes reducidos, queries separadas TRAIN/VAL, `Dataset` único reutilizado). Ver `terraform/workstation.tf`.

---

## Bugs Corregidos Durante el Desarrollo

1. **`.gitignore` excluía `src/models/` por error** — el patrón `models/` sin anclar a la raíz (sin `/` inicial) matcheaba cualquier carpeta llamada `models` en cualquier nivel, incluyendo `src/models/`, y excluía silenciosamente el código fuente de esa carpeta de git.
2. **`suppress_warnings=True` anulaba la detección de fallos en ARIMA clásico** — con `suppress_warnings=True`, `pmdarima.auto_arima` no emitía el `ConvergenceWarning` que la lógica de detección de fallos necesitaba capturar; cambiado a `False` (el ruido en consola es la señal que el script necesita).
3. **`maxiter` insuficiente** — el default de `auto_arima` (`maxiter=50`) causaba 21/32 fallos espurios de convergencia ("Maximum Likelihood optimization failed to converge", idéntico en todas las series, señal de un límite de iteraciones agotado, no de 21 series genuinamente problemáticas). Subido a `maxiter=200`; el resultado final (30/32) confirmó que era el optimizador, no los datos.
4. **BigQuery no soporta `JOIN ... ON` con subquery ni `IN` de tupla directa** — al filtrar `features_train` contra `lgbm_sample` por `(item_id, store_id)`, ni `WHERE (item_id, store_id) IN (SELECT ...)` ni un `JOIN` con subquery en la condición funcionan tal cual; solución en ambos casos: envolver las columnas en `STRUCT(item_id, store_id) IN (SELECT STRUCT(item_id, store_id) FROM ...)`.

---

## Tablas de Predicciones — Esquema Común

Las 3 tablas de predicciones comparten esquema `(item_id, store_id, date, p05, p25, p50, p75, p95)` para que Fase 6 pueda comparar los 3 modelos directamente:

| Modelo | Tabla predicciones | Tabla metadata | Series |
|---|---|---|---|
| 4a ARIMA clásico | `arima_predictions` | `arima_metadata` | 32 (estratificada) |
| 4b BQML ARIMA_PLUS | `bqml_predictions` | `bqml_metadata` | 30,490 (completas) |
| 4c LightGBM Cuantil | `predictions_lgbm` | — | ~3,000 (`lgbm_sample`, proporcional) |

---

## Commits Relevantes

- `ba06fc8` — fix: .gitignore excluia src/models/ por patron 'models/' sin anclar a raiz (+ `arima_baseline.py`)
- `68c967a` — fix: suppress_warnings=False en auto_arima para no anular deteccion de ConvergenceWarning
- `adfa3ed` — fix: aumenta maxiter a 200
- `c9e78e0` — feat: BQML ARIMA_PLUS (Fase 4b) - entrenamiento + prediccion con cuantiles derivados
- `0d798e3` — docs+feat: Fase 4b - validacion bqml_predictions, bqml_metadata, hallazgo NaN en series muy_lento
- `74a4b3e` — feat: LightGBM Quantile (Fase 4c) - smoke test, 5 modelos por percentil
- `00f3ef9` — fix: memoria - dtypes float32, queries separadas TRAIN/VAL (OOM en e2-standard-4)
- `40bd968` — fix: OOM en train_models() - free_raw_data=True, Dataset unico reutilizado para los 5 quantiles
- `988619a` — fix: int8/int16 normales (no nullable) para evitar posible rechazo de LightGBM en downcast de memoria
- `7a76cb2` — fix: subir Workstation a e2-highmem-4 (32GB) - e2-standard-4 tumbaba la VM por OOM en Fase 4c
- `f676fae` — feat: muestra proporcional lgbm_sample (~3000 series) para viabilidad de tiempo en 4c/5
- `14e12a0` — feat: filtrar LightGBM a lgbm_sample (~3000 series) en vez de las 30490 completas
- `6938b47` — fix: BigQuery no soporta IN de tupla directa - usar STRUCT(item_id, store_id)
- `a0e992f` — docs: cerrar Fase 4c con resultados reales - lgbm_sample, e2-highmem-4, fix STRUCT IN

---

## Próxima Fase: FASE 5 — Walk-forward CV

**Estado:** ⏳ No iniciada.

**Objetivo (referencia):** Validación robusta con **5 folds fijos espaciados** (no los ~54 folds posibles con `window_size=365`/paso de 28 días — por viabilidad de tiempo/costo), reutilizando exactamente la misma lógica de entrenamiento de los 3 modelos ya construida en Fase 4:
- ARIMA clásico sobre las 32 series de `arima_sample`
- BQML ARIMA_PLUS sobre las 30,490 series completas
- LightGBM Cuantil sobre `lgbm_sample` (~3,000 series)

---

## Notas

- El test set (últimos 28 días, `sales_train_evaluation.csv`) permanece bloqueado — no se carga a BigQuery hasta Fase 6.
- Las 32 series de `arima_sample` están garantizadas dentro de `lgbm_sample` (forzadas en `sql/build_lgbm_sample.sql`) — condición necesaria para que la Tabla A de Fase 6 (comparación de los 3 modelos sobre las mismas 32 series) sea válida.
- ARIMA clásico queda fuera de la Tabla B de Fase 6 (30,490 series, BQML vs. LightGBM) por diseño — nunca se entrenó a esa escala (ver Fase 4a).
