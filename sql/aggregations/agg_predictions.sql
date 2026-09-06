-- ============================================================================
-- Fase 8 (revisado Fase 9) -- agg_predictions
-- Predicciones LightGBM (modelo ganador) + venta real agregadas por
-- dia/categoria/tienda -- incluye actual_sales para poder calcular error
-- (heatmap categoria x tienda, pagina 3 del dashboard).
--
-- CAMBIO respecto al diseno original: en vez de combinar los 5 folds de
-- walk-forward CV (dispersos 2011-2016) con el test set real, esta version
-- se acota a la ventana continua de 56 dias fold5 + test real
-- (2016-03-28 -> 2016-05-22) -- la unica combinacion de periodos que es
-- realmente contigua en el tiempo, apta para graficar como serie temporal
-- sin huecos ni saltos.
--
-- Bug encontrado al construir el dashboard: predictions_lgbm_cv corre sobre
-- lgbm_sample (~3,001 series) pero predictions_test (Fase 7, Tarea 4) corrio
-- sobre las 30,490 series completas. Sumar/promediar ambas fuentes sin
-- normalizar el universo de series producia un salto de escala ~10x justo
-- en el empalme (2016-04-24 -> 2016-04-25) que no reflejaba ningun cambio
-- real de demanda. Fix: INNER JOIN de predictions_test contra lgbm_sample
-- para acotarlo al mismo universo de ~3,001 series que fold 5.
--
-- actual_sales se agrega con AVG (no SUM) para ser comparable directamente
-- contra p50 -- ambos son "venta promedio por serie", mismo criterio que
-- ya se usaba para las columnas de prediccion en esta tabla (a diferencia
-- de agg_weekly_comparison, que usa SUM porque responde una pregunta de
-- demanda total, no de error por serie).
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
  WHERE fold_id = 5
  UNION ALL
  SELECT p.item_id, p.store_id, p.date, p.p05, p.p25, p.p50, p.p75, p.p95
  FROM `mle-m5-forecast.m5_dataset.predictions_test` p
  INNER JOIN `mle-m5-forecast.m5_dataset.lgbm_sample` s
    ON p.item_id = s.item_id AND p.store_id = s.store_id
),
actual_combined AS (
  SELECT item_id, store_id, date, sales
  FROM `mle-m5-forecast.m5_dataset.sales_long`
  UNION ALL
  SELECT item_id, store_id, date, sales
  FROM `mle-m5-forecast.m5_dataset.test_labels`
)
SELECT
  c.date,
  seg.category,
  c.store_id,
  AVG(a.sales) AS actual_sales,
  AVG(c.p05) AS p05,
  AVG(c.p25) AS p25,
  AVG(c.p50) AS p50,
  AVG(c.p75) AS p75,
  AVG(c.p95) AS p95
FROM combined c
JOIN actual_combined a
  ON c.item_id = a.item_id AND c.store_id = a.store_id AND c.date = a.date
JOIN `mle-m5-forecast.m5_dataset.series_segments` seg
  ON c.item_id = seg.item_id AND c.store_id = seg.store_id
GROUP BY c.date, seg.category, c.store_id;
