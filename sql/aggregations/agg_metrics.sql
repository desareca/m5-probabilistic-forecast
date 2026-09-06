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
-- Filas adicionales 'lgbm_test_real': el Pinball Loss real del test set
-- (Fase 7, predictions_test) desglosado por categoria FOODS/HOBBIES/
-- HOUSEHOLD -- soporta directamente el hallazgo de Fase 7 (~20% mas alto
-- en el test real que en CV) como grafico comparativo en el dashboard,
-- ahora comparable categoria a categoria contra los folds de CV (antes
-- solo existia como una fila agregada category='ALL', porque
-- test_evaluation_metrics de Fase 7 nunca desgloso por categoria -- ver
-- src/evaluation/build_test_metrics_by_category.py, Fase 9, que recalcula
-- esto desde predictions_test + test_labels + series_segments sin tocar
-- el resultado original de Fase 7).
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
  category,
  quantile_name AS quantile,
  avg_pinball_loss AS pinball_loss,
  CURRENT_DATE() AS run_date
FROM `mle-m5-forecast.m5_dataset.test_evaluation_metrics_by_category`;
