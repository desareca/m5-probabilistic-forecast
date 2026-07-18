-- ============================================================================
-- Muestra estratificada de 32 series para el smoke test de ARIMA clasico
-- (Fase 4a) -- 8 series por cada categoria_zero_rate (rapido/medio/lento/
-- muy_lento), a traves de las 10 tiendas y 3 categorias de producto.
--
-- Deliberadamente NO proporcional a la distribucion real (que es 78%
-- lento+muy_lento) -- el objetivo es cubrir el rango completo de regimenes
-- de intermitencia con la misma cantidad de evidencia por regimen, para
-- poder reportar "de 8 series muy_lento, ARIMA convergio en X" de forma
-- comparable entre categorias. Ver INSTRUCCIONES.md Fase 4a.
--
-- Requiere: m5_dataset.series_segments ya construida
--   (sql/build_series_segments.sql).
--
-- Reproducibilidad: GoogleSQL RAND() NO acepta semilla (a diferencia de
-- SQL Server/MySQL) -- usar FARM_FINGERPRINT sobre una clave fija en vez de
-- RAND() para que la muestra sea la misma en cada corrida, no una distinta
-- cada vez que se re-ejecuta la query.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.arima_sample` AS

SELECT * EXCEPT(rn)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY categoria_zero_rate
      ORDER BY FARM_FINGERPRINT(CONCAT(item_id, '_', store_id, '_arima_sample_v1'))
    ) AS rn
  FROM `mle-m5-forecast.m5_dataset.series_segments`
)
WHERE rn <= 8;

-- Validacion esperada tras correr:
--   32 filas totales (8 por categoria_zero_rate x 4 categorias)
--   Re-correr esta query debe dar exactamente las mismas 32 series cada vez
--   (a diferencia de si se hubiera usado RAND()) -- confirmar con:
--
-- SELECT categoria_zero_rate, COUNT(*) AS n_series
-- FROM `mle-m5-forecast.m5_dataset.arima_sample`
-- GROUP BY categoria_zero_rate
-- ORDER BY categoria_zero_rate;
