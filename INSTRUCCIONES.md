# M5 Probabilistic Forecasting — Instrucciones para Claude Code

## Contexto del proyecto

Proyecto de MLE en GCP. El objetivo es construir un pipeline end-to-end de forecasting probabilístico sobre el dataset M5 (Walmart), considerando ingeniería de features, modelado cuantil, MLOps en Vertex AI y visualización en Looker Studio.

**Entorno de trabajo:**
- Editor: Cloud Workstations (VS Code en navegador)
- Cloud: GCP (proyecto `mle-m5-forecast`)
- Python: 3.10+
- Control de versiones: Git + GitHub

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Almacenamiento raw | Google Cloud Storage (GCS) |
| Data warehouse | BigQuery |
| Feature engineering | BigQuery SQL + Python |
| Baseline estadístico | statsmodels ARIMA |
| Baseline cloud | BigQuery ML ARIMA_PLUS |
| Modelo challenger | LightGBM Quantile |
| Entrenamiento | Vertex AI Custom Training |
| MLOps | Vertex AI Pipelines + Model Registry |
| Predicciones | Vertex AI Batch Prediction |
| Dashboard | Looker Studio |
| Infraestructura | Terraform |

---

## Estructura del repositorio

```
m5-probabilistic-forecast/
├── data/
│   └── raw/                    # CSVs descargados de Kaggle (no commitear)
├── notebooks/
│   ├── 01_eda.ipynb
│   └── 02_evaluation.ipynb
├── src/
│   ├── data/
│   │   └── load_to_bq.py       # Carga GCS → BigQuery
│   ├── features/
│   │   ├── temporal_features.sql
│   │   ├── fourier_features.py
│   │   └── price_features.sql
│   ├── models/
│   │   ├── arima_baseline.py   # statsmodels, muestra pequeña
│   │   ├── baseline_bqml.sql   # BQML ARIMA_PLUS
│   │   └── lgbm_quantile.py    # LightGBM cuantil
│   └── evaluation/
│       └── metrics.py          # Pinball Loss + comparativas
├── pipelines/
│   ├── m5_pipeline.py          # Vertex AI Pipeline KFP
│   ├── training_job.py         # Custom Training Job
│   ├── batch_predict.py        # Batch Prediction Job
│   └── register_model.py       # Model Registry
├── sql/
│   └── aggregations/           # Tablas agregadas para Looker Studio
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Fases del proyecto

### Fase 1 — Setup GCP ✅ COMPLETADA

**Objetivo:** Infraestructura base lista para trabajar.

**Tareas:**
1. ✅ Crear proyecto GCP `mle-m5-forecast`
2. ✅ Habilitar APIs (BigQuery, Vertex AI, Cloud Storage, Artifact Registry)
3. ✅ Inicializar repositorio Git con estructura de carpetas
4. ✅ Terraform: GCS bucket `mle-m5-forecast-m5-bucket` + dataset BigQuery `m5_dataset`
5. ✅ Service account `mle-m5-sa` con roles IAM (BigQuery Admin, Storage Admin, AI Platform Admin)

**Recursos creados:**
- GCS Bucket: `mle-m5-forecast-m5-bucket` (us-central1)
- BigQuery Dataset: `m5_dataset` (us-central1)
- Service Account: `mle-m5-sa`

---

### Fase 2 — Datos ✅ COMPLETADA

**Objetivo:** Datos M5 cargados en BigQuery listos para exploración.

**Tareas:**
1. ✅ Descargar dataset M5 Uncertainty desde Kaggle
2. ✅ Subir CSVs crudos a GCS
3. ✅ Cargar a BigQuery en formato original (wide)
4. ✅ Reshape wide → long en BigQuery SQL (58,327,370 filas → tabla `m5_dataset.sales_long`)
5. ✅ EDA en notebook (`notebooks/01_eda.ipynb`):
   - Distribución de ventas por categoría
   - Tasa de ceros por item/tienda
   - Variación de precio en el tiempo
   - Distribución de eventos del calendario
   - Patrones estacionales (semanal, mensual, anual)
   - Autocorrelación (ACF) para decidir `window_size`

**Hallazgos clave del EDA (ver notebook para detalle completo):**
- 78.4% de las series tienen ≥50% de días en cero — confirma LightGBM Quantile sobre ARIMA puro
- Coeficiente de variación de precios real: 62–91% según categoría
- Estacionalidad semanal clara (sáb/dom por encima de entre-semana) → justifica Fourier `period=7`
- Tendencia anual ascendente marcada: +57% entre 2011 y 2016 (parcial)
- **Walmart cierra cada 25 de diciembre** — la serie agregada cae a cero ese día todos los años.
  Debe tratarse como caso especial determinístico en la feature de eventos de Fase 3, no como
  un evento más
- ACF (serie detrended): meseta 0.42–0.44 entre lag=365 y lag=546 (eco anual real), pero colapsa
  a ~0 en lag=730 — evidencia directa para fijar `window_size = 365` (ver Fase 5)

**Archivos fuente M5:**
- `sales_train_validation.csv` — 30,490 filas × 1,919 columnas (día `d_1`–`d_1913`, hasta 2016-04-24)
- `sell_prices.csv` — ~6.8M filas
- `calendar.csv` — 1,969 filas

**⚠️ Decisión de diseño — qué archivo de ventas cargar:**
Se carga **únicamente `sales_train_validation.csv`** (1,913 días) a `sales_wide`/`sales_long`
durante las Fases 2–6. `sales_train_evaluation.csv` (1,941 días, hasta 2016-06-19) ya está
disponible en GCS (`raw/sales_train_evaluation.csv`) pero **no se carga a BigQuery hasta la
Fase 6**, y solo para extraer los últimos 28 días (`d_1914`–`d_1941`) como ground truth del
TEST set. Esto garantiza que el TEST set esté bloqueado físicamente — no existe en BigQuery
hasta la evaluación final — en vez de depender solo de disciplina de código para no tocarlo.

**Entregable:** Notebook EDA completo (`notebooks/01_eda.ipynb`).

---

### Fase 3 — Feature Engineering

**Objetivo:** Tabla de features lista para entrenamiento, sin data leakage.

**Regla crítica:** Toda feature debe respetar el corte temporal. Los lags y rolling features deben calcularse con `ORDER BY date` y nunca mirar hacia el futuro del punto de predicción.

**Features a construir en BigQuery SQL:**

```
Temporales:
- lag_7, lag_14, lag_28 (ventas de hace N días)
- roll_mean_7, roll_mean_28 (promedio móvil)
- roll_std_28 (volatilidad)
- día de semana, mes, año, semana del año

Fourier (estacionalidad):
- sin/cos para period=7 (semanal), n_terms=3
- sin/cos para period=365 (anual), n_terms=5

Precio:
- precio actual
- precio relativo a media histórica del item
- momentum de precio (variación últimas 4 semanas)

Eventos:
- flag de evento (binario)
- tipo de evento (cultural, sporting, nacional, religiosa)
- días antes/después del evento
```

**Entregable:** Tabla `m5_dataset.features_train` con todas las features, documentación de cada feature y su justificación.

---

### Fase 4 — Modelos

**Objetivo:** Tres modelos entrenados y guardados, listos para evaluación comparativa.

#### 4a. ARIMA clásico (statsmodels)

- Trabajar con submuestra: 1 tienda (CA_1), categoría FOODS
- Entrenar un ARIMA por serie temporal
- Guardar predicciones puntuales e intervalos de confianza
- Documentar limitaciones: no escala, intervalos asumen normalidad

```python
from statsmodels.tsa.arima.model import ARIMA
# Un modelo por serie: item_id + store_id
```

#### 4b. BQML ARIMA_PLUS

- Mismo concepto escalado a las 30,490 series completas
- Entrenado 100% en BigQuery SQL
- Usar `holiday_region = 'US'`
- Extraer predicciones con `ML.FORECAST`

```sql
CREATE OR REPLACE MODEL m5_dataset.baseline_arima
OPTIONS(
  model_type = 'ARIMA_PLUS',
  time_series_timestamp_col = 'date',
  time_series_data_col = 'sales',
  time_series_id_col = ['item_id', 'store_id'],
  holiday_region = 'US'
) AS ...
```

#### 4c. LightGBM Cuantil

- Un modelo por percentil: P5, P25, P50, P75, P95
- `objective='quantile'`, `alpha=q`
- Entrenado en Vertex AI Custom Training Job (n1-standard-8)
- Artefactos guardados en GCS

```python
params = {
    'objective': 'quantile',
    'alpha': q,
    'n_estimators': 1000,
    'learning_rate': 0.05,
    'num_leaves': 127,
}
```

**Entregable:** 3 modelos entrenados, predicciones guardadas en BigQuery.

---

### Fase 5 — Validación

**Objetivo:** Esquema de validación robusto sin data leakage.

**Esquema temporal:**
```
Total: 1,941 días (2011-01-29 → 2016-06-19)

[========== TRAIN + CV ==========][== VAL ==][== TEST ==]
        ~1,885 días                  28 días    28 días
[----------- sales_train_validation.csv (1,913 días) -----------][+28 evaluation]

TEST: bloqueado hasta evaluación final (nunca tocar antes) — vive solo en
      sales_train_evaluation.csv, que no se carga a BigQuery hasta Fase 6
VAL: para selección de hiperparámetros y modelo — últimos 28 días de
     sales_train_validation.csv, sí disponible en BigQuery desde Fase 2
CV: walk-forward rolling window, folds de 28 días, dentro de TRAIN+CV
```

Nota: los 1,913 días de `sales_train_validation.csv` (que sí está cargado en BigQuery)
cubren exactamente TRAIN + CV + VAL. Los 28 días de TEST son la diferencia con
`sales_train_evaluation.csv` (1,941 días) y permanecen fuera de BigQuery hasta la Fase 6.

**Walk-forward CV:**
- Rolling window (el train tiene tamaño fijo, se desplaza hacia adelante)
- El tamaño de la ventana de train se define durante el EDA (Fase 2)
- Horizonte de predicción: 28 días por fold
- Aplicar a los 3 modelos con la misma lógica y mismo tamaño de ventana
- Para LightGBM: regenerar features respetando el corte temporal de cada fold

**Decisión tomada (post-EDA): `window_size = 365` días.** Justificación: la ACF de la serie
agregada (detrended) muestra una meseta de 0.42–0.44 entre lag=365 y lag=546 (eco anual real,
sobrevive al detrend), pero colapsa a ~0 en lag=730. Una ventana de 730 días diluiría la señal
reciente con historia sin correlación real, además de arrastrar el nivel de ventas más bajo de
años tempranos (tendencia +57% entre 2011 y 2016). Ver `notebooks/01_eda.ipynb`, sección 9.

**Entregable:** Función `walk_forward_cv()` reutilizable con parámetro `window_size` configurable, métricas por fold para cada modelo.

---

### Fase 6 — Evaluación

**Objetivo:** Comparativa honesta entre los 3 modelos.

**Paso previo — habilitar el TEST set:** cargar `sales_train_evaluation.csv` (ya está en
`raw/` en GCS) a una tabla nueva `m5_dataset.sales_wide_evaluation`, hacer reshape a long,
y quedarse **solo** con `d_1914`–`d_1941` (2016-04-25 → 2016-06-19) como
`m5_dataset.test_labels`. No usar el resto de las columnas de este archivo para nada más —
son idénticas a `sales_train_validation.csv` en `d_1`–`d_1913`.

**Métrica principal:** Weighted Scaled Pinball Loss (métrica oficial M5 Uncertainty)

```python
def pinball_loss(y_true, y_pred, quantile):
    error = y_true - y_pred
    return np.mean(np.maximum(quantile * error, (quantile - 1) * error))
```

**Análisis requerido:**
- Pinball Loss por modelo × percentil
- Pinball Loss por categoría (FOODS, HOBBIES, HOUSEHOLD)
- Análisis de casos difíciles:
  - Series con >50% ceros
  - Productos nuevos sin historia
  - Semanas con eventos especiales
- Tabla comparativa final: ARIMA → BQML → LightGBM

**Entregable:** Notebook `02_evaluation.ipynb` con todas las comparativas y análisis de errores.

---

### Fase 7 — MLOps

**Objetivo:** Pipeline reproducible y modelo registrado en Vertex AI.

**Tareas:**
1. Empaquetar training en Docker y subir a Artifact Registry
2. Registrar modelo en Vertex AI Model Registry con métricas
3. Crear Vertex AI Pipeline (KFP) con los pasos:
   - `ingest_component` → carga datos frescos
   - `features_component` → regenera features
   - `train_component` → entrena LightGBM
   - `evaluate_component` → calcula métricas
   - `register_component` → registra si mejora baseline
4. Batch Prediction Job sobre datos de test
5. Cloud Scheduler para disparar pipeline mensualmente

**Entregable:** Pipeline YAML compilado, modelo en Model Registry, job de batch prediction funcionando.

---

### Fase 8 — Tablas agregadas

**Objetivo:** Tablas livianas en BigQuery optimizadas para Looker Studio.

**Tablas a crear (post batch prediction):**

```sql
-- 1. Predicciones agregadas por día/categoría
m5_dataset.agg_predictions
  (date, category, store_id, p05, p25, p50, p75, p95)

-- 2. Métricas por modelo
m5_dataset.agg_metrics
  (model, category, quantile, pinball_loss, run_date)

-- 3. Real vs predicho semanal
m5_dataset.agg_weekly_comparison
  (week, category, actual_sales, pred_p50, pred_p05, pred_p95)
```

**Reglas de diseño:**
- Solo columnas necesarias para el dashboard
- Particionadas por fecha
- Resultado: tablas de miles de filas, no millones
- Queries desde Looker Studio < 1MB procesado

**Entregable:** 3 tablas agregadas en BigQuery, queries de creación documentadas.

---

### Fase 9 — Dashboard Looker Studio

**Objetivo:** Dashboard público compartible que muestre los resultados.

**Conexión:** Looker Studio → BigQuery → tablas agregadas

**Visualizaciones:**
1. Predicción P50 vs ventas reales (línea temporal)
2. Bandas de incertidumbre P5/P95 (área sombreada)
3. Comparativa Pinball Loss por modelo (barras)
4. Heatmap de error por categoría × tienda
5. Filtros: categoría, tienda, rango de fechas

**Entregable:** Dashboard público con link compartible.

---

### Fase 10 — Presentación del proyecto

**Objetivo:** Proyecto presentable para portfolio y entrevistas.

**Tareas:**
1. README.md completo:
   - Descripción del problema
   - Diagrama de arquitectura GCP
   - Instrucciones de reproducción
   - Resultados principales (tabla de métricas)
   - Link al dashboard
2. Diagrama de arquitectura (draw.io o similar)
3. Notebook `02_evaluation.ipynb` limpio y narrativo
4. `.gitignore` correctamente configurado (excluir data raw, credenciales)
5. GitHub repo público

---

## Decisiones de diseño importantes

- **Forecasting probabilístico sobre puntual:** El negocio necesita intervalos para decisiones de inventario, no solo valores esperados.
- **Pinball Loss como métrica:** Penaliza asimétricamente — subestimar stock tiene diferente costo que sobreestimar.
- **Tablas agregadas para dashboard:** Minimiza costo de BigQuery queries desde Looker Studio.
- **Batch prediction sobre online serving:** Más barato para portfolio; apropiado para horizonte de 28 días.
- **Walk-forward CV:** Obligatorio para series temporales — K-Fold clásico introduce data leakage.
- **Test set bloqueado:** Los últimos 28 días no se tocan hasta la evaluación final.

---

## Costos estimados

| Componente | Costo estimado |
|---|---|
| BigQuery storage + queries dev | ~$0–2 |
| Vertex AI Training (LightGBM, n1-standard-8, ~2hr) | ~$0.80 |
| Vertex AI Batch Prediction (1 job) | ~$1–2 |
| GCS storage | ~$0.10 |
| Cloud Workstations (~$0.60/hr, uso activo) | Variable |
| Looker Studio | Gratis |
| **Total estimado** | **~$10–15 USD** |

Con $300 de crédito inicial de GCP: costo efectivo $0.

---

## Notas para Claude Code

- Autenticación via Application Default Credentials (ADC) — ya configurada en la Workstation
- Toda query BigQuery en Python usar `google-cloud-bigquery` con `project` explícito
- Guardar artefactos intermedios en GCS, no local
- Commitear frecuentemente con mensajes descriptivos
- No commitear credenciales, data raw ni archivos de modelo grandes
- **Apagar la Workstation cuando no se esté trabajando** para controlar costos
