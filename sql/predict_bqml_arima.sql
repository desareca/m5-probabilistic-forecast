-- ============================================================================
-- Fase 4b — BQML ARIMA_PLUS: prediccion sobre el fold VAL (ultimos 28 dias)
--
-- Usa ML.FORECAST sobre `baseline_arima` (ver sql/train_bqml_arima.sql) y
-- deriva los 5 cuantiles (p05/p25/p50/p75/p95) desde forecast_value +
-- standard_error asumiendo normalidad -- mismo criterio que
-- src/models/arima_baseline.py (Fase 4a, scipy.stats.norm.ppf), para que la
-- comparacion de Fase 6 sea consistente entre los 3 modelos.
--
-- BigQuery no tiene una funcion nativa de inversa de la normal estandar, asi
-- que los z-scores de p05/p25/p75/p95 se hardcodean -- son constantes fijas
-- de la distribucion normal estandar, no dependen de los datos ni del modelo:
--   z(0.05) = -1.6448536269514722      z(0.25) = -0.6744897501960817
--   z(0.75) =  0.6744897501960817      z(0.95) =  1.6448536269514722
-- p50 = forecast_value directo (media = mediana bajo normalidad, z=0).
--
-- horizon=28 porque el fold VAL es de 28 dias (igual que 4a). confidence_level
-- solo afecta los bounds nativos de ML.FORECAST (prediction_interval_*), que
-- aqui no se usan -- los cuantiles se derivan directo de standard_error.
--
-- clip(0, None): GREATEST(x, 0) evita cuantiles negativos en series con
-- ventas bajas/intermitentes, igual que en 4a.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.bqml_predictions` AS

WITH forecast AS (
  SELECT
    item_id,
    store_id,
    DATE(forecast_timestamp) AS date,
    forecast_value,
    standard_error
  FROM ML.FORECAST(
    MODEL `mle-m5-forecast.m5_dataset.baseline_arima`,
    STRUCT(28 AS horizon, 0.95 AS confidence_level)
  )
)

SELECT
  item_id,
  store_id,
  date,
  GREATEST(forecast_value + (-1.6448536269514722) * standard_error, 0) AS p05,
  GREATEST(forecast_value + (-0.6744897501960817) * standard_error, 0) AS p25,
  GREATEST(forecast_value, 0)                                          AS p50,
  GREATEST(forecast_value + ( 0.6744897501960817) * standard_error, 0) AS p75,
  GREATEST(forecast_value + ( 1.6448536269514722) * standard_error, 0) AS p95
FROM forecast;
