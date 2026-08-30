-- ============================================================================
-- Fase 8 -- agg_weekly_comparison
-- Real vs. predicho semanal por categoria (SUM de venta agregada, no AVG --
-- responde "cuanta demanda total" por semana/categoria, la pregunta de
-- negocio real para decisiones de inventario).
--
-- Combina sales_long + test_labels (ventas reales) con predictions_lgbm_cv
-- + predictions_test (predicciones), mismo criterio de union que
-- agg_predictions.sql -- ambas fuentes cubren exactamente las mismas
-- fechas (folds de CV + test set), asi que el JOIN INNER no pierde filas
-- por asimetria de cobertura.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.agg_weekly_comparison`
PARTITION BY week
AS
WITH actual_combined AS (
  SELECT item_id, store_id, date, sales
  FROM `mle-m5-forecast.m5_dataset.sales_long`
  UNION ALL
  SELECT item_id, store_id, date, sales
  FROM `mle-m5-forecast.m5_dataset.test_labels`
),
pred_combined AS (
  SELECT item_id, store_id, date, p05, p50, p95
  FROM `mle-m5-forecast.m5_dataset.predictions_lgbm_cv`
  UNION ALL
  SELECT item_id, store_id, date, p05, p50, p95
  FROM `mle-m5-forecast.m5_dataset.predictions_test`
),
joined AS (
  SELECT
    p.date,
    seg.category,
    a.sales AS actual_sales,
    p.p05,
    p.p50,
    p.p95
  FROM pred_combined p
  JOIN actual_combined a
    ON p.item_id = a.item_id AND p.store_id = a.store_id AND p.date = a.date
  JOIN `mle-m5-forecast.m5_dataset.series_segments` seg
    ON p.item_id = seg.item_id AND p.store_id = seg.store_id
)
SELECT
  DATE_TRUNC(date, WEEK(MONDAY)) AS week,
  category,
  SUM(actual_sales) AS actual_sales,
  SUM(p50) AS pred_p50,
  SUM(p05) AS pred_p05,
  SUM(p95) AS pred_p95
FROM joined
GROUP BY week, category;
