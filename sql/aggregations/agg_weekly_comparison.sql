-- ============================================================================
-- Fase 8 (revisado Fase 9) -- agg_weekly_comparison
-- Real vs. predicho semanal por categoria (SUM de venta agregada, no AVG --
-- responde "cuanta demanda total" por semana/categoria, la pregunta de
-- negocio real para decisiones de inventario).
--
-- CAMBIO respecto al diseno original: acotado a la ventana continua de
-- 56 dias fold5 + test real (2016-03-28 -> 2016-05-22), no a los 5 folds
-- de CV dispersos 2011-2016 + test. Esa version original producia un
-- grafico de serie temporal con "islas" (huecos de anos entre folds) sin
-- sentido para visualizar como tendencia -- ver discusion Fase 9.
--
-- Bug encontrado y corregido: predictions_lgbm_cv corre sobre lgbm_sample
-- (~3,001 series) pero predictions_test corrio sobre las 30,490 series
-- completas (Fase 7, Tarea 4) -- sumarlas sin normalizar el universo de
-- series producia un salto de escala ~10x justo en el empalme
-- (2016-04-24 -> 2016-04-25). Fix: INNER JOIN de predictions_test contra
-- lgbm_sample, igual que en agg_predictions.sql, para que ambos tramos
-- de la ventana compartan exactamente el mismo universo de ~3,001 series
-- tanto en las predicciones como en la venta real (via el JOIN con
-- actual_combined mas abajo, que hereda el filtro por construccion).
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
  SELECT item_id, store_id, date, p05, p25, p50, p75, p95
  FROM `mle-m5-forecast.m5_dataset.predictions_lgbm_cv`
  WHERE fold_id = 5
  UNION ALL
  SELECT p.item_id, p.store_id, p.date, p.p05, p.p25, p.p50, p.p75, p.p95
  FROM `mle-m5-forecast.m5_dataset.predictions_test` p
  INNER JOIN `mle-m5-forecast.m5_dataset.lgbm_sample` s
    ON p.item_id = s.item_id AND p.store_id = s.store_id
),
joined AS (
  SELECT
    p.date,
    seg.category,
    a.sales AS actual_sales,
    p.p05,
    p.p25,
    p.p50,
    p.p75,
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
  SUM(p25) AS pred_p25,
  SUM(p75) AS pred_p75,
  SUM(p95) AS pred_p95
FROM joined
GROUP BY week, category;
