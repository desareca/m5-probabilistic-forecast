-- ============================================================================
-- Fase 4b — Validacion de m5_dataset.bqml_predictions
--
-- Ejecutar cada bloque por separado (no es un script multi-declaracion),
-- despues de haber corrido sql/train_bqml_arima.sql y sql/predict_bqml_arima.sql.
--
-- Contexto: el chequeo de monotonicidad (2) encontro 616 "violaciones" que
-- resultaron ser un falso positivo -- ver diagnostico completo mas abajo.
-- El hallazgo real (NaN en standard_error para 22 series) llevo a crear
-- m5_dataset.bqml_metadata (ver sql/build_bqml_metadata.sql).
-- ============================================================================

-- 1. Conteo de filas: 30,490 series x 28 dias = 853,720
-- Resultado real: filas=853720, series=30490, dias=28 -- OK, coincide exacto
SELECT
  COUNT(*) AS filas,
  COUNT(DISTINCT CONCAT(item_id, '_', store_id)) AS series,
  COUNT(DISTINCT date) AS dias
FROM `mle-m5-forecast.m5_dataset.bqml_predictions`;

-- 2. Monotonicidad de cuantiles: se esperaba 0 filas (ninguna violacion),
-- porque los 5 cuantiles se derivan de una sola formula
-- (forecast_value + z*standard_error) con z-scores ya ordenados -- esa
-- construccion es monotona por diseno mientras standard_error sea un
-- numero real.
-- Resultado real: 616 filas. Ver diagnostico abajo -- no fue un cruce de
-- cuantiles real.
SELECT COUNT(*) AS violaciones_monotonicidad
FROM `mle-m5-forecast.m5_dataset.bqml_predictions`
WHERE NOT (p05 <= p25 AND p25 <= p50 AND p50 <= p75 AND p75 <= p95);

-- 3. Valores negativos: el GREATEST(x, 0) de predict_bqml_arima.sql deberia
-- garantizar 0.
-- Resultado real: 0 -- OK
SELECT COUNT(*) AS valores_negativos
FROM `mle-m5-forecast.m5_dataset.bqml_predictions`
WHERE p05 < 0 OR p25 < 0 OR p50 < 0 OR p75 < 0 OR p95 < 0;

-- ============================================================================
-- DIAGNOSTICO de las 616 "violaciones" de (2)
-- ============================================================================

-- 4. Inspeccion directa de las filas marcadas como violacion.
-- Resultado real: p05/p25/p75/p95 = NaN, p50 = valor valido. No es un
-- standard_error negativo (eso daria numeros reales pero "raros", no NaN) --
-- es standard_error = NaN en si mismo. En BigQuery (IEEE 754), cualquier
-- comparacion con NaN devuelve FALSE, incluso NaN <= NaN, por eso el WHERE
-- NOT(...) de (2) las conto como "violacion" sin serlo en el sentido de un
-- cruce real de cuantiles.
SELECT
  item_id, store_id, date,
  p05, p25, p50, p75, p95,
  (p95 - p50) AS diferencia_p95_p50
FROM `mle-m5-forecast.m5_dataset.bqml_predictions`
WHERE NOT (p05 <= p25 AND p25 <= p50 AND p50 <= p75 AND p75 <= p95)
ORDER BY item_id, store_id, date
LIMIT 20;

-- 5. Alcance real del problema. OJO: p05 IS NULL da 0 falsamente -- NaN no
-- es NULL en SQL, hay que usar IS_NAN().
-- Resultado real: 22 series afectadas, 616 filas (22 x 28 = 616 exacto --
-- son series completas afectadas, no dias sueltos dentro de series sanas).
SELECT
  COUNT(DISTINCT CONCAT(item_id, '_', store_id)) AS series_afectadas,
  COUNT(*) AS filas_afectadas
FROM `mle-m5-forecast.m5_dataset.bqml_predictions`
WHERE IS_NAN(p05);

-- 6. Que tienen en comun las 22 series afectadas -- cruce contra
-- series_segments (Fase 4a).
-- Resultado real: 20/22 son categoria muy_lento (tasa_ceros 85-97%), las
-- otras 2 son lento en el extremo alto (76-78%). Mismo patron que la falla
-- de convergencia en ARIMA clasico (4a): la intermitencia extrema rompe la
-- estimacion de incertidumbre. Pero la tasa de fallo es mucho menor aca:
-- 20 de 11,783 series muy_lento del dataset completo = 0.17%, vs 12.5%
-- (1 de 8) en la muestra de ARIMA clasico -- BQML ARIMA_PLUS parece mucho
-- mas robusto a escala, probablemente por su pipeline interno (STL, manejo
-- de spikes/dips) que suaviza casos degenerados antes de estimar varianza.
SELECT
  seg.categoria_zero_rate,
  seg.tasa_ceros,
  seg.venta_promedio,
  pred.item_id,
  pred.store_id
FROM (
  SELECT DISTINCT item_id, store_id
  FROM `mle-m5-forecast.m5_dataset.bqml_predictions`
  WHERE IS_NAN(p05)
) pred
JOIN `mle-m5-forecast.m5_dataset.series_segments` seg
  ON pred.item_id = seg.item_id AND pred.store_id = seg.store_id
ORDER BY seg.tasa_ceros DESC;
