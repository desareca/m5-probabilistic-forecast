-- ============================================================================
-- Muestra representativa (~3,000 series) para entrenar LightGBM en Fase 4c/5
--
-- A diferencia de m5_dataset.arima_sample (32 series, BALANCEADA entre
-- categorias de zero-rate -- proposito: comparar regimenes de intermitencia
-- con la misma evidencia cada uno), esta muestra es PROPORCIONAL a la
-- distribucion real del dataset completo. El proposito es distinto:
-- aproximar el comportamiento de LightGBM a escala completa (30,490 series)
-- sin pagar el costo de tiempo de entrenar sobre todas -- no estudiar
-- categorias por separado. Por eso debe reflejar la mezcla real (~78%
-- lento+muy_lento), no una mezcla artificial pareja.
--
-- IMPORTANTE: incluye SIEMPRE las 32 series de arima_sample. La Tabla A de
-- Fase 6 (comparacion de 3 modelos sobre las mismas 32 series) filtra las
-- predicciones de LightGBM por esas 32 series -- si se muestrearan de forma
-- totalmente independiente, no habria garantia de que las 32 cayeran dentro
-- de esta muestra. Se fuerzan primero, y se completa la cuota proporcional
-- de cada categoria con el resto.
--
-- Tamanos objetivo por categoria (proporcionales a series_segments,
-- N=3000 total, incluyendo las de arima_sample):
--   lento:      12,133 / 30,490 x 3000 = ~1,194 (8 ya vienen de arima_sample)
--   muy_lento:  11,783 / 30,490 x 3000 = ~1,160 (8 de arima_sample)
--   medio:       5,500 / 30,490 x 3000 = ~541  (8 de arima_sample)
--   rapido:      1,074 / 30,490 x 3000 = ~106  (8 de arima_sample)
--   Total: ~3,001 series (32 garantizadas + ~2,969 adicionales)
--
-- Reproducibilidad: FARM_FINGERPRINT, no RAND() (RAND() no acepta semilla
-- en GoogleSQL -- ver sql/build_arima_sample.sql para el mismo criterio).
--
-- Requiere: m5_dataset.series_segments y m5_dataset.arima_sample ya
-- construidas.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.lgbm_sample` AS

WITH objetivo_por_categoria AS (
  SELECT categoria_zero_rate, n_objetivo FROM UNNEST([
    STRUCT('lento' AS categoria_zero_rate, 1194 AS n_objetivo),
    STRUCT('muy_lento', 1160),
    STRUCT('medio', 541),
    STRUCT('rapido', 106)
  ])
),

-- Las 32 series de arima_sample, garantizadas en la muestra
forzadas AS (
  SELECT seg.*
  FROM `mle-m5-forecast.m5_dataset.series_segments` seg
  INNER JOIN `mle-m5-forecast.m5_dataset.arima_sample` a
    ON seg.item_id = a.item_id AND seg.store_id = a.store_id
),

-- El resto del pool, excluyendo las ya forzadas, rankeado para completar
-- la cuota proporcional de cada categoria
resto_rankeado AS (
  SELECT
    seg.*,
    ROW_NUMBER() OVER (
      PARTITION BY seg.categoria_zero_rate
      ORDER BY FARM_FINGERPRINT(CONCAT(seg.item_id, '_', seg.store_id, '_lgbm_sample_v1'))
    ) AS rn
  FROM `mle-m5-forecast.m5_dataset.series_segments` seg
  LEFT JOIN `mle-m5-forecast.m5_dataset.arima_sample` a
    ON seg.item_id = a.item_id AND seg.store_id = a.store_id
  WHERE a.item_id IS NULL  -- excluye las 32 ya forzadas
),

completadas AS (
  SELECT r.* EXCEPT(rn)
  FROM resto_rankeado r
  JOIN objetivo_por_categoria o USING (categoria_zero_rate)
  -- 8 de cada categoria ya vienen de arima_sample -- se completa con
  -- (n_objetivo - 8) adicionales del resto del pool
  WHERE r.rn <= (o.n_objetivo - 8)
)

SELECT * FROM forzadas
UNION ALL
SELECT * FROM completadas;

-- Validacion esperada tras correr:
--   ~3,001 filas totales, sin duplicados de (item_id, store_id)
--   Las 32 series de arima_sample deben estar TODAS presentes
--   Proporciones por categoria similares al dataset completo (no
--   balanceadas como arima_sample)
--
-- SELECT categoria_zero_rate, COUNT(*) AS n_series,
--   ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 4) AS pct_muestra
-- FROM `mle-m5-forecast.m5_dataset.lgbm_sample`
-- GROUP BY categoria_zero_rate
-- ORDER BY categoria_zero_rate;
--
-- SELECT COUNT(*) AS arima_series_incluidas
-- FROM `mle-m5-forecast.m5_dataset.arima_sample` a
-- INNER JOIN `mle-m5-forecast.m5_dataset.lgbm_sample` l
--   ON a.item_id = l.item_id AND a.store_id = l.store_id;
-- -- debe dar 32
