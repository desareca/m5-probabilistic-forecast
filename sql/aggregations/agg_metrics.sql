-- ============================================================================
-- Fase 8 -- agg_metrics
-- Pinball Loss por modelo x categoria x percentil, para el grafico de
-- barras comparativo del dashboard (INSTRUCCIONES.md, Fase 9).
--
-- Fuente principal: cv_metrics_by_product_category (Fase 6), filtrada a
-- in_arima_sample = TRUE -- el UNICO alcance donde los 3 modelos son
-- comparables entre si (32 series presentes en ARIMA/BQML/LightGBM; ver
-- phase-summaries/06-evaluacion.md, "el split de dos alcances es
-- obligatorio"). Usar el alcance completo (~3,000 series) mezclaria una
-- comparacion de 2 modelos con una de 3 en la misma tabla sin poder
-- distinguirlas facilmente en Looker Studio.
--
-- Filas adicionales 'lgbm_test_real' (category='ALL'): el Pinball Loss real
-- del test set (Fase 7, test_evaluation_metrics) al lado de la estimacion
-- de CV -- soporta directamente el hallazgo de Fase 7 (~20% mas alto en el
-- test real que en CV) como grafico comparativo en el dashboard.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.agg_metrics` AS

SELECT
  model,
  category,
  quantile_name AS quantile,
  avg_pinball_loss AS pinball_loss,
  CURRENT_DATE() AS run_date
FROM `mle-m5-forecast.m5_dataset.cv_metrics_by_product_category`
WHERE in_arima_sample = TRUE

UNION ALL

SELECT
  'lgbm_test_real' AS model,
  'ALL' AS category,
  quantile_name AS quantile,
  pinball_loss,
  CURRENT_DATE() AS run_date
FROM `mle-m5-forecast.m5_dataset.test_evaluation_metrics`
WHERE quantile_name != 'avg';
