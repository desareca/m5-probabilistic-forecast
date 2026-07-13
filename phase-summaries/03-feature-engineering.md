# Fase 3: Feature Engineering — Resumen Completado

**Fecha inicio:** 2026-07-13
**Fecha fin:** 2026-07-13
**Estado:** ✅ COMPLETADA

---

## Objetivo

Construir la tabla de features para entrenamiento (`m5_dataset.features_train`) sobre `sales_long` + `calendar` + `sell_prices`, respetando el corte temporal en cada feature — sin data leakage.

---

## Tareas Completadas

### 1. Generador de features Fourier
- ✅ `src/features/fourier_features.py` — genera dinámicamente las 22 columnas Fourier (semanal `n_terms=3`, semestral `n_terms=3`, anual `n_terms=5`) en vez de escribirlas a mano
- ✅ Usa `days_since_start` como índice temporal: un contador de día calendario **global** (mismo valor para todas las series en una fecha dada), no un índice por serie — evita que la fase de seno/coseno se desalinee entre series con distinta fecha de primera venta

### 2. Construcción de `features_train`
- ✅ `sql/build_features_train.sql` — `CREATE OR REPLACE TABLE` sobre `sales_long` + `calendar` + `sell_prices`
- ✅ Grain: `(item_id, store_id, date)`, igual que `sales_long`
- ✅ Particionada por `date`, clusterizada por `item_id, store_id`
- ✅ Todas las window functions de ventas/precio con `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` (nunca `CURRENT ROW`)

### 3. Validación sobre muestra (CA_1)
- ✅ `sql/validate_features_train_sample.sql` — 3 checks independientes, corridos manualmente en la Workstation contra la tabla ya construida

---

## Resultado del Build

| Métrica | Valor |
|---|---|
| Tabla | `m5_dataset.features_train` |
| Filas | 58,327,370 (igual a `sales_long`) |
| Series | 30,490 (3,049 items × 10 tiendas) |
| Particionado | `date` |
| Clusterizado | `item_id, store_id` |

---

## Features Incluidas

Lista completa y justificación de cada una en `INSTRUCCIONES.md`, Fase 3. Resumen:

**Temporales:** `lag_7`, `lag_14`, `lag_28`, `lag_182`, `roll_mean_7`, `roll_mean_28`, `roll_std_28`, `day_of_week`, `day_of_month`, `month`, `year`, `week_of_year`, `days_since_start`, `days_since_last_sale`, `pct_zeros_28d`

**Fourier (22 columnas):** semanal (period=7, n=3), semestral (period=182.625, n=3), anual (period=365.25, n=5)

**Precio:** `sell_price`, `price_rel_mean` (ventana móvil de 365 días, no expandida), `price_momentum_4w`, `lag_price_28`, `price_changed`

**Eventos:** `is_event`, `event_type` (Navidad recodificada como `'Store_Closure'`), `days_to_next_event`, `days_from_last_event`, `is_christmas`, `snap_active` (derivado del prefijo de `store_id`)

---

## Validación — 3 Checks (todos pasados)

### (a) No leakage
`lag_7` y `roll_mean_28` recalculados a mano contra `sales_long` en 3 fechas no consecutivas (día ~100, ~500, ~1000) de la serie de mayor volumen en CA_1 — coinciden exactamente con los valores de la tabla.

### (b) `snap_active` selecciona el estado correcto
Verificado en fechas donde `snap_CA`, `snap_TX` y `snap_WI` difieren entre sí — `snap_active` en CA_1 toma consistentemente `snap_CA`, nunca los otros dos estados.

### (c) `price_rel_mean` usa ventana móvil, no expandida
Comparado el cálculo de ventana móvil (365 días) contra un promedio expandido manual, en 2 fechas separadas por >1,500 días — los valores difieren claramente (1.52 vs 1.38 en la media, diferencia de ~0.11 en `price_rel_mean`), confirmando que la ventana es móvil y no acumula todo el historial.

---

## Bugs Corregidos Durante el Desarrollo

1. **`ORDER BY` final incompatible con `PARTITION BY` en `CREATE TABLE ... AS SELECT`** — BigQuery no lo permite; removido. `CLUSTER BY item_id, store_id` cumple el mismo propósito de organización física sin necesitar el `ORDER BY`.
2. **Subquery con referencia a tabla dentro de `JOIN ON`** — no soportado por BigQuery en `sql/validate_features_train_sample.sql`; movido a `WHERE`.
3. **`price_changed` devolvía `0` en vez de `NULL`** cuando el precio actual (`sell_price`) es `NULL` — corregido para devolver `NULL` (desconocido) en ese caso, evitando reportar falsamente "sin cambio" cuando en realidad el precio del día es desconocido.

---

## Decisión de Diseño Reafirmada

`features_train` es consumida **únicamente** por LightGBM Quantile (Fase 4c). ARIMA clásico y BQML ARIMA_PLUS trabajan directo sobre `sales_long` (serie univariada) y no consumen esta tabla. Por eso los `NULL`s en columnas de lag/rolling al inicio de cada serie no representan un problema — LightGBM los maneja nativamente y no hay un segundo consumidor que requiera imputación.

---

## Commits Relevantes

- `7fb729b` — feat: build features_train SQL (Fase 3) + validacion sobre CA_1
- `fix: quitar ORDER BY final (incompatible con PARTITION BY en CREATE TABLE)`
- `fix: mover subquery de item_id a WHERE (BigQuery no soporta subquery con tabla en JOIN ON)`
- `fix: DISTINCT en check (b) para output mas legible (misma cobertura de validacion)`

---

## Próxima Fase: FASE 4 — Modelos

**Estado:** ⏳ No iniciada.

**Objetivo (referencia):** Tres modelos entrenados y guardados, listos para evaluación comparativa:
- **4a. ARIMA clásico (statsmodels)** — submuestra CA_1, categoría FOODS
- **4b. BQML ARIMA_PLUS** — escala completa (30,490 series), `holiday_region = 'US'`
- **4c. LightGBM Cuantil** — P5/P25/P50/P75/P95, entrenado en Vertex AI Custom Training, consume `features_train`

---

## Notas

- El test set (últimos 28 días, `sales_train_evaluation.csv`) permanece bloqueado — no se carga a BigQuery hasta Fase 6.
- `features_train` no requiere imputación de NULLs al inicio de cada serie: único consumidor es LightGBM.
