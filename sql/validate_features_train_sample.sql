-- ============================================================================
-- Validacion manual de m5_dataset.features_train sobre 1 tienda (CA_1)
--
-- Este archivo contiene 3 SELECT independientes (no es un script
-- multi-declaracion) -- correr cada bloque por separado en la consola de
-- BigQuery, uno a la vez, DESPUES de haber corrido sql/build_features_train.sql.
--
-- Requiere: m5_dataset.features_train ya construida.
--
-- (a) No leakage: lag_7 / roll_mean_28 recalculados a mano contra sales_long
--     para 3 fechas reales de la serie de mayor volumen en CA_1.
-- (b) snap_active selecciona snap_CA (no snap_TX ni snap_WI) para CA_1.
-- (c) price_rel_mean usa ventana movil de 365 dias, no expandida.
-- ============================================================================


-- ============================================================================
-- CHECK (a) — No leakage en lag_7 y roll_mean_28
--
-- Se usa el item de mayor volumen en CA_1 (para tener ventas con variacion
-- real dia a dia, no series intermitentes donde cualquier promedio da ~0).
-- Se comparan 3 fechas no consecutivas (dia ~100, ~500 y ~1000 de la serie)
-- contra un calculo manual sobre sales_long:
--   - manual_lag_7        = sales en (fecha - 7 dias), calculado con DATE_SUB
--   - manual_roll_mean_28 = AVG(sales) entre (fecha - 28) y (fecha - 1), es
--                           decir EXCLUYENDO el dia de la fila (fecha misma)
-- Si features_train hubiera usado CURRENT ROW en vez de 1 PRECEDING en el
-- roll_mean_28, o hubiera desplazado el lag mal, alguno de los 3 valores no
-- calzaria con el calculo manual (elegimos fechas no consecutivas para tener
-- variabilidad real de ventas ese dia vs. el promedio de los 28 anteriores).
--
-- Resultado esperado: lag_7_matches = TRUE y roll_mean_28_matches = TRUE en
-- las 3 filas.
-- ============================================================================

WITH sample_item AS (
  SELECT item_id
  FROM `mle-m5-forecast.m5_dataset.sales_long`
  WHERE store_id = 'CA_1'
  GROUP BY item_id
  ORDER BY SUM(sales) DESC
  LIMIT 1
),

series_numbered AS (
  SELECT
    date,
    sales,
    ROW_NUMBER() OVER (ORDER BY date) AS rn
  FROM `mle-m5-forecast.m5_dataset.sales_long`
  WHERE store_id = 'CA_1'
    AND item_id = (SELECT item_id FROM sample_item)
),

check_dates AS (
  SELECT date, rn AS day_index_in_series
  FROM series_numbered
  WHERE rn IN (100, 500, 1000)
),

manual_calc AS (
  SELECT
    cd.date AS check_date,
    cd.day_index_in_series,
    (
      SELECT sl.sales
      FROM `mle-m5-forecast.m5_dataset.sales_long` sl
      WHERE sl.store_id = 'CA_1'
        AND sl.item_id = (SELECT item_id FROM sample_item)
        AND sl.date = DATE_SUB(cd.date, INTERVAL 7 DAY)
    ) AS manual_lag_7,
    (
      SELECT AVG(sl.sales)
      FROM `mle-m5-forecast.m5_dataset.sales_long` sl
      WHERE sl.store_id = 'CA_1'
        AND sl.item_id = (SELECT item_id FROM sample_item)
        AND sl.date BETWEEN DATE_SUB(cd.date, INTERVAL 28 DAY) AND DATE_SUB(cd.date, INTERVAL 1 DAY)
    ) AS manual_roll_mean_28
  FROM check_dates cd
)

SELECT
  mc.check_date,
  mc.day_index_in_series,
  mc.manual_lag_7,
  ft.lag_7 AS features_train_lag_7,
  mc.manual_lag_7 = ft.lag_7 AS lag_7_matches,
  ROUND(mc.manual_roll_mean_28, 6) AS manual_roll_mean_28,
  ROUND(ft.roll_mean_28, 6) AS features_train_roll_mean_28,
  ABS(mc.manual_roll_mean_28 - ft.roll_mean_28) < 1e-9 AS roll_mean_28_matches
FROM manual_calc mc
JOIN `mle-m5-forecast.m5_dataset.features_train` ft
  ON ft.date = mc.check_date
WHERE ft.store_id = 'CA_1'
  AND ft.item_id = (SELECT item_id FROM sample_item)
ORDER BY mc.check_date;


-- ============================================================================
-- CHECK (b) — snap_active usa snap_CA (no snap_TX ni snap_WI) para CA_1
--
-- Se contrastan fechas del calendario donde snap_CA difiere de snap_TX y/o
-- snap_WI -- si snap_active estuviera tomando la columna equivocada, estas
-- fechas lo expondrian inmediatamente (en una fecha donde snap_CA=1 y
-- snap_TX=0, snap_active deberia ser 1, no 0).
--
-- Resultado esperado: matches_snap_CA = TRUE en todas las filas.
-- ============================================================================

WITH contrast_dates AS (
  SELECT date, snap_CA, snap_TX, snap_WI
  FROM `mle-m5-forecast.m5_dataset.calendar`
  WHERE snap_CA != snap_TX OR snap_CA != snap_WI
  ORDER BY date
  LIMIT 10
)

SELECT
  ft.date,
  ft.store_id,
  ft.snap_active,
  cd.snap_CA,
  cd.snap_TX,
  cd.snap_WI,
  ft.snap_active = cd.snap_CA AS matches_snap_CA
FROM `mle-m5-forecast.m5_dataset.features_train` ft
JOIN contrast_dates cd
  ON ft.date = cd.date
WHERE ft.store_id = 'CA_1'
ORDER BY ft.date;

-- Chequeo adicional: conteo global de discrepancias para todas las tiendas
-- CA (deberia ser 0 filas / mismatches = 0).
-- SELECT COUNT(*) AS mismatches
-- FROM `mle-m5-forecast.m5_dataset.features_train` ft
-- JOIN `mle-m5-forecast.m5_dataset.calendar` c ON ft.date = c.date
-- WHERE ft.store_id LIKE 'CA%' AND ft.snap_active != c.snap_CA;


-- ============================================================================
-- CHECK (c) — price_rel_mean usa ventana movil de 365 dias, no expandida
--
-- Se toman 2 fechas del mismo item en CA_1, separadas por mas de 365 dias
-- (la mas temprana con al menos ~365 dias de historia de precio detras, para
-- que su ventana movil ya este "llena"). Para cada fecha se recalculan a
-- mano DOS promedios:
--   - manual_moving_avg_365 : AVG(sell_price) entre (fecha-365) y (fecha-1)
--                             -- deberia coincidir con lo que produjo la tabla
--   - manual_expanding_mean : AVG(sell_price) de TODO el historial anterior
--                             a la fecha (lo que habria pasado si la ventana
--                             hubiera sido expandida en vez de movil)
--
-- Resultado esperado:
--   - recomputed_price_rel_mean ≈ price_rel_mean_from_table (confirma que la
--     tabla efectivamente usa la ventana movil de 365 dias)
--   - manual_moving_avg_365 y manual_expanding_mean_alt son DISTINTOS entre si
--     (confirma que la ventana movil no es lo mismo que acumular todo el
--     historial -- si fueran iguales, no habria diferencia real entre usar
--     ventana movil o expandida)
--   - manual_moving_avg_365 tambien difiere entre las dos fechas (no es un
--     valor fijo que se repite)
-- ============================================================================

WITH sample_item AS (
  SELECT item_id
  FROM `mle-m5-forecast.m5_dataset.sales_long`
  WHERE store_id = 'CA_1'
  GROUP BY item_id
  ORDER BY SUM(sales) DESC
  LIMIT 1
),

priced_dates AS (
  SELECT date, sell_price
  FROM `mle-m5-forecast.m5_dataset.features_train`
  WHERE store_id = 'CA_1'
    AND item_id = (SELECT item_id FROM sample_item)
    AND sell_price IS NOT NULL
),

early_date AS (
  -- primera fecha con precio, mas un margen de 400 dias para asegurar que
  -- la ventana movil de 365 dias ya este completa (no arrancando)
  SELECT date
  FROM priced_dates
  WHERE date >= DATE_ADD((SELECT MIN(date) FROM priced_dates), INTERVAL 400 DAY)
  ORDER BY date
  LIMIT 1
),

late_date AS (
  SELECT date
  FROM priced_dates
  ORDER BY date DESC
  LIMIT 1
),

two_dates AS (
  SELECT date FROM early_date
  UNION ALL
  SELECT date FROM late_date
),

manual_checks AS (
  SELECT
    td.date,
    (
      SELECT AVG(ft2.sell_price)
      FROM `mle-m5-forecast.m5_dataset.features_train` ft2
      WHERE ft2.store_id = 'CA_1'
        AND ft2.item_id = (SELECT item_id FROM sample_item)
        AND ft2.date BETWEEN DATE_SUB(td.date, INTERVAL 365 DAY) AND DATE_SUB(td.date, INTERVAL 1 DAY)
    ) AS manual_moving_avg_365,
    (
      SELECT AVG(ft2.sell_price)
      FROM `mle-m5-forecast.m5_dataset.features_train` ft2
      WHERE ft2.store_id = 'CA_1'
        AND ft2.item_id = (SELECT item_id FROM sample_item)
        AND ft2.date < td.date
    ) AS manual_expanding_mean
  FROM two_dates td
)

SELECT
  ft.date,
  DATE_DIFF((SELECT date FROM late_date), (SELECT date FROM early_date), DAY) AS days_between_checks,
  ft.sell_price,
  ROUND(ft.price_rel_mean, 6) AS price_rel_mean_from_table,
  ROUND(mc.manual_moving_avg_365, 4) AS manual_moving_avg_365,
  ROUND(SAFE_DIVIDE(ft.sell_price, mc.manual_moving_avg_365), 6) AS recomputed_price_rel_mean,
  ROUND(mc.manual_expanding_mean, 4) AS manual_expanding_mean_alt,
  ROUND(SAFE_DIVIDE(ft.sell_price, mc.manual_expanding_mean), 6) AS ratio_if_it_were_expanding
FROM `mle-m5-forecast.m5_dataset.features_train` ft
JOIN manual_checks mc ON ft.date = mc.date
WHERE ft.store_id = 'CA_1'
  AND ft.item_id = (SELECT item_id FROM sample_item)
ORDER BY ft.date;
