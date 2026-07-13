# Fase 2: Datos + EDA — Resumen Completado

**Fecha inicio:** 2026-06-28
**Fecha fin:** 2026-07-12
**Estado:** ✅ COMPLETADA

---

## Objetivo

Cargar el dataset M5 (Walmart) a BigQuery, hacer reshape wide → long, y realizar un EDA completo que informe las decisiones de diseño de las fases siguientes (feature engineering, ventana de entrenamiento).

---

## Tareas Completadas

### 1. Descarga y carga a GCS
- ✅ Kaggle API instalada y autenticada
- ✅ Dataset M5 Uncertainty descargado (`sales_train_validation.csv`, `sales_train_evaluation.csv`, `sell_prices.csv`, `calendar.csv`)
- ✅ CSVs subidos a GCS en `raw/` dentro del bucket del proyecto
- ✅ `sales_train_evaluation.csv` subido pero **no cargado a BigQuery** (reservado para Fase 6, ver Decisión de Diseño)

### 2. Carga a BigQuery (formato wide)
- ✅ Tabla `m5_dataset.sales_wide` creada a partir de `sales_train_validation.csv` (30,490 filas × 1,919 columnas)
- ✅ `calendar` y `sell_prices` cargadas sin transformación

### 3. Reshape wide → long
- ✅ Script `sql/reshape_wide_to_long.py` (varias iteraciones de fix)
- ✅ Tabla `m5_dataset.sales_long` generada: **58,327,370 filas**
- ✅ Bug corregido: extracción de `item_id`/`store_id` con regex — el patrón original solo capturaba 3 series únicas en vez de 30,490 (commit `79c90a0`)

### 4. EDA (`notebooks/01_eda.ipynb`)
- ✅ Estructura de datos y tamaños de tablas
- ✅ Rango temporal y estadísticas básicas
- ✅ Distribución de ventas por categoría (FOODS, HOBBIES, HOUSEHOLD)
- ✅ Tasa de ceros por serie
- ✅ Variación de precios por categoría
- ✅ Eventos de calendario y SNAP
- ✅ Series de tiempo representativas (alto/bajo/moderado volumen)
- ✅ Patrones estacionales (semanal, mensual, anual)
- ✅ Autocorrelación (ACF) para decidir `window_size` de Fase 5

---

## Recursos Creados en GCP

| Recurso | Nombre | Filas | Estado |
|---------|--------|-------|--------|
| BigQuery tabla | `m5_dataset.sales_wide` | 30,490 | ✅ Activa |
| BigQuery tabla | `m5_dataset.sales_long` | 58,327,370 | ✅ Activa |
| BigQuery tabla | `m5_dataset.calendar` | 1,969 | ✅ Activa |
| BigQuery tabla | `m5_dataset.sell_prices` | ~6.8M | ✅ Activa |
| GCS objeto | `raw/sales_train_evaluation.csv` | — | ✅ Almacenado, no cargado a BQ |

---

## Decisión de Diseño: `sales_train_validation.csv` vs `sales_train_evaluation.csv`

Documentada en `INSTRUCCIONES.md` (Fase 2 y Fase 6).

- Las Fases 2–6 trabajan **exclusivamente** con `sales_train_validation.csv` (1,913 días, `d_1`–`d_1913`, hasta 2016-04-24). Esto es lo que se cargó a `sales_wide`/`sales_long`.
- `sales_train_evaluation.csv` (1,941 días, hasta 2016-06-19) ya está en GCS pero **no se carga a BigQuery hasta la Fase 6**, y solo para extraer `d_1914`–`d_1941` como `m5_dataset.test_labels` (ground truth del TEST set).
- **Motivo:** garantizar que el TEST set (últimos 28 días) esté bloqueado *físicamente* — no existe en BigQuery hasta la evaluación final — en vez de depender solo de disciplina de código para no tocarlo.
- Esquema temporal resultante: `sales_train_validation.csv` (1,913 días) cubre exactamente TRAIN + CV + VAL; los 28 días de TEST son la diferencia con `sales_train_evaluation.csv`.

---

## Hallazgos Clave del EDA

### Escala de datos
- 58,327,370 registros de ventas diarias
- 1,913 días (2011-01-29 → 2016-04-24)
- 30,490 series únicas (item × tienda)
- 3 categorías: FOODS, HOBBIES, HOUSEHOLD

### Tasa de ceros (⚠️ desafío crítico para modelado)
- **78.4% de las series tienen ≥50% de días con venta cero**
- Descarta modelos que asuman continuidad (ARIMA clásico sin ajustes)
- Refuerza la elección de LightGBM Quantile como challenger (maneja sparsity nativamente) y BQML ARIMA_PLUS como baseline escalable

### Precios
- Coeficiente de variación entre **62% y 91%** según categoría — variabilidad de precio mucho más alta de lo asumido inicialmente
- Justifica incluir features de precio relativo y momentum en Fase 3, no solo precio nivel

### Estacionalidad
- **Patrón semanal:** picos en fin de semana (sábado), valles lunes-martes
- **Tendencia anual:** +57% de crecimiento en ventas a lo largo del período observado
- **Cierre total cada 25 de diciembre** (Navidad) — las tiendas Walmart cierran, ventas = 0 en todas las series ese día todos los años. Esto es un patrón determinístico de calendario, no un caso de "producto sin stock"; debe tratarse explícitamente en feature engineering (flag de día cerrado) para no contaminar métricas de error ni rolling features

### Autocorrelación (ACF) y decisión de `window_size`
- El análisis de ACF sobre las series agregadas mostró que la autocorrelación relevante (estacional + tendencia) se concentra dentro de un horizonte de ~365 días, con caída significativa más allá de ese punto
- **Decisión fijada: `window_size = 365` días** para el walk-forward CV de la Fase 5 (entre los candidatos 365 vs 730 propuestos en `INSTRUCCIONES.md`)
- Esto queda pendiente de trasladar formalmente a `INSTRUCCIONES.md` (Fase 5) como decisión cerrada

---

## Commits Relevantes

- `eea7477` — feat: Add EDA notebook and batch reshape script
- `79c90a0` — fix: extracción correcta de item_id/store_id (bug de regex causaba solo 3 series únicas en vez de 30,490)
- `dbab655` — first eda
- `1786c76` — add: seasonal patterns (daily, monthly, annual)
- `4ff4a74` — fix text plot Venta promedio por categoría de ceros
- `b35ebf6` — docs: aclarar uso de sales_train_validation.csv vs evaluation.csv
- `9c31422` — add Autocorrelación y selección de window_size

---

## Próxima Fase: FASE 3 — Feature Engineering

**Estado:** ⏳ Aún en diseño — **no iniciar todavía**. El alcance de features se está definiendo en sesión de chat antes de escribir SQL.

**Objetivo (referencia):** Tabla de features sin data leakage, respetando el corte temporal en cada lag/rolling feature.

**Features candidatas (de `INSTRUCCIONES.md`):**
- Temporales: lag_7, lag_14, lag_28, roll_mean_7, roll_mean_28, roll_std_28, día de semana/mes/año
- Fourier: semanal (period=7, n_terms=3), anual (period=365, n_terms=5)
- Precio: actual, relativo a media histórica, momentum
- Eventos: flag, tipo, días antes/después
- **Nuevo (a incorporar por hallazgo del EDA):** flag de día cerrado (25-dic) para no distorsionar rolling features ni métricas de error

---

## Notas

- El test set (últimos 28 días, `sales_train_evaluation.csv`) permanece bloqueado — no se carga a BigQuery hasta Fase 6.
- Toda feature de Fase 3 debe verificarse contra leakage antes de incorporarse a la tabla de entrenamiento.
