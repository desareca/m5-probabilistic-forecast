-- ============================================================================
-- Fase 4b — m5_dataset.bqml_metadata
--
-- Tabla espejo de m5_dataset.arima_metadata (Fase 4a): documenta, por serie,
-- si BQML ARIMA_PLUS pudo estimar incertidumbre (p05/p25/p75/p95) o no.
-- No hay fallback silencioso -- el fallo en si es parte del hallazgo, mismo
-- criterio que en 4a (ver INSTRUCCIONES.md Fase 4a: "el fallo en si es un
-- hallazgo del experimento").
--
-- Contexto (ver sql/validate_bqml_predictions.sql para el diagnostico
-- completo): 22 de 30,490 series (0.07%) tienen standard_error = NaN en
-- ML.FORECAST, lo que produce p05/p25/p75/p95 = NaN (p50 si queda valido,
-- viene directo de forecast_value sin depender de standard_error). 20 de
-- esas 22 son categoria_zero_rate = muy_lento, las otras 2 son lento en el
-- extremo alto -- mismo patron de fondo que la no convergencia de ARIMA
-- clasico en series intermitentes (4a), pero con una tasa de fallo mucho
-- menor (0.17% de las series muy_lento, vs 12.5% en la muestra de 4a).
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.bqml_metadata` AS

SELECT DISTINCT
  pred.item_id,
  pred.store_id,
  seg.categoria_zero_rate,
  seg.tasa_ceros,
  IS_NAN(pred.p05) AS fallo_incertidumbre
FROM `mle-m5-forecast.m5_dataset.bqml_predictions` pred
JOIN `mle-m5-forecast.m5_dataset.series_segments` seg
  ON pred.item_id = seg.item_id AND pred.store_id = seg.store_id;

-- Validacion esperada tras correr:
--   30,490 filas totales (una por serie, igual que series_segments)
--   fallo_incertidumbre = TRUE en exactamente 22 filas
--
-- SELECT fallo_incertidumbre, COUNT(*) FROM `mle-m5-forecast.m5_dataset.bqml_metadata`
-- GROUP BY fallo_incertidumbre;
