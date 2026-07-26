-- ============================================================================
-- Fase 4b — BQML ARIMA_PLUS (baseline_arima)
--
-- Escala el mismo concepto de 4a (ARIMA por serie) a las 30,490 series
-- completas de sales_long, entrenado 100% en BigQuery SQL. A diferencia de
-- 4a (statsmodels/pmdarima sobre una muestra de 32 series con ventana de
-- entrenamiento acotada a 365 dias por tratabilidad computacional),
-- ARIMA_PLUS corre su propio pipeline (STL, holiday effects, manejo de
-- spikes) sobre el historial completo -- no hay razon de escala para
-- restringir la ventana aqui.
--
-- Fold unico (smoke test de Fase 4, ver INSTRUCCIONES.md): TRAIN = todo el
-- historial de sales_long hasta antes de VAL, VAL = ultimos 28 dias del
-- rango disponible. Fase 5 reutiliza esta misma logica de entrenamiento
-- para el walk-forward completo.
--
-- holiday_region = 'US' porque los datos son de Walmart USA.
-- auto_arima_max_order = 4 (default es 5): reduce el multiplicador de costo
-- de 42x a 30x. Ver tabla de costos en INSTRUCCIONES.md, Fase 4b.
--
-- ⚠️ Costo estimado de este CREATE MODEL: ~$15.94 (BQML time-series models
-- se cobran a $312.50/TiB, no la tarifa normal de $6.25/TiB de queries; el
-- auto_arima interno multiplica por la cantidad de modelos candidato
-- evaluados -- 30x con auto_arima_max_order=4 sobre ~1.87 GB de columnas
-- necesarias de sales_long). Confirmar antes de correr.
-- ============================================================================

CREATE OR REPLACE MODEL `mle-m5-forecast.m5_dataset.baseline_arima`
OPTIONS(
  model_type = 'ARIMA_PLUS',
  time_series_timestamp_col = 'date',
  time_series_data_col = 'sales',
  time_series_id_col = ['item_id', 'store_id'],
  holiday_region = 'US',
  auto_arima_max_order = 4
) AS

WITH val_cutoff AS (
  -- Mismo esquema temporal que 4a: VAL = ultimos 28 dias disponibles en
  -- sales_long, TRAIN = todo lo anterior. val_start = MAX(date) - 27 dias
  -- (28 dias inclusive, igual que VAL_DAYS en src/models/arima_baseline.py).
  SELECT DATE_SUB(MAX(date), INTERVAL 27 DAY) AS val_start
  FROM `mle-m5-forecast.m5_dataset.sales_long`
)

SELECT
  s.item_id,
  s.store_id,
  s.date,
  s.sales
FROM `mle-m5-forecast.m5_dataset.sales_long` AS s
CROSS JOIN val_cutoff
WHERE s.date < val_cutoff.val_start;
