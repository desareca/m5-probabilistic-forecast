-- ============================================================================
-- Segmentacion de series por tasa de ceros (categoria_zero_rate)
--
-- Construye m5_dataset.series_segments: una fila por (item_id, store_id) con
-- estadisticas resumen de toda la serie -- NO el grain diario de features_train.
-- Sirve para dos propositos:
--   1. Muestreo estratificado para ARIMA clasico (Fase 4a, ver
--      sql/build_arima_sample.sql)
--   2. Analisis de casos dificiles en Fase 6 ("series con >50% ceros"), ya
--      pedido explicitamente por INSTRUCCIONES.md sin necesidad de recalcular
--
-- category se deriva de item_id (patron {CATEGORIA}_{DEPT}_{NUM}, ej.
-- FOODS_1_001) via SPLIT -- sales_long no trae la columna category directa,
-- se perdio en el reshape wide->long.
--
-- Cortes de categoria_zero_rate (calzan con los buckets reales usados en el
-- EDA, notebooks/01_eda.ipynb seccion "Tasa de ceros"):
--   rapido     : tasa_ceros < 0.20
--   medio      : 0.20 <= tasa_ceros < 0.50
--   lento      : 0.50 <= tasa_ceros < 0.80
--   muy_lento  : tasa_ceros >= 0.80
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.series_segments` AS

SELECT
  item_id,
  store_id,
  SPLIT(item_id, '_')[OFFSET(0)] AS category,
  AVG(CASE WHEN sales = 0 THEN 1.0 ELSE 0.0 END) AS tasa_ceros,
  AVG(sales) AS venta_promedio,
  CASE
    WHEN AVG(CASE WHEN sales = 0 THEN 1.0 ELSE 0.0 END) < 0.20 THEN 'rapido'
    WHEN AVG(CASE WHEN sales = 0 THEN 1.0 ELSE 0.0 END) < 0.50 THEN 'medio'
    WHEN AVG(CASE WHEN sales = 0 THEN 1.0 ELSE 0.0 END) < 0.80 THEN 'lento'
    ELSE 'muy_lento'
  END AS categoria_zero_rate
FROM `mle-m5-forecast.m5_dataset.sales_long`
GROUP BY item_id, store_id;

-- Validacion esperada tras correr (ver analisis ya hecho sobre esta misma
-- query sin guardar, sesion de diseno de Fase 4):
--   30,490 filas totales, sin duplicados de (item_id, store_id)
--   category: FOODS 14,370 / HOUSEHOLD 10,470 / HOBBIES 5,650
--   categoria_zero_rate: lento 12,133 / muy_lento 11,783 / medio 5,500 / rapido 1,074
--   tasa_ceros siempre en [0,1], venta_promedio siempre >= 0
