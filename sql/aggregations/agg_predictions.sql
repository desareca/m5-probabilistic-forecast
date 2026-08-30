-- ============================================================================
-- Fase 8 -- agg_predictions
-- Predicciones LightGBM (modelo ganador) agregadas por dia/categoria/tienda.
-- Combina los 5 folds de walk-forward CV (Fase 5, historia dispersa
-- 2011-2016) + el test set real (Fase 7, unico periodo nunca visto) --
-- ambos son predicciones de LightGBM, nunca mezclados con ARIMA/BQML aca
-- (esta tabla es "la" serie de prediccion para el dashboard, no una
-- comparativa de modelos -- esa es agg_metrics).
--
-- Particionada por date, sin item_id/store_id-level detail (agregado a
-- categoria x tienda) -- columnas minimas para Looker Studio, por diseno
-- (ver skill-bigquery-ml.md, "Columnas minimas en tablas agregadas").
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.agg_predictions`
PARTITION BY date
AS
WITH combined AS (
  SELECT item_id, store_id, date, p05, p25, p50, p75, p95
  FROM `mle-m5-forecast.m5_dataset.predictions_lgbm_cv`
  UNION ALL
  SELECT item_id, store_id, date, p05, p25, p50, p75, p95
  FROM `mle-m5-forecast.m5_dataset.predictions_test`
)
SELECT
  c.date,
  seg.category,
  c.store_id,
  AVG(c.p05) AS p05,
  AVG(c.p25) AS p25,
  AVG(c.p50) AS p50,
  AVG(c.p75) AS p75,
  AVG(c.p95) AS p95
FROM combined c
JOIN `mle-m5-forecast.m5_dataset.series_segments` seg
  ON c.item_id = seg.item_id AND c.store_id = seg.store_id
GROUP BY c.date, seg.category, c.store_id;
