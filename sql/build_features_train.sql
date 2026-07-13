-- ============================================================================
-- Fase 3 — Feature Engineering
-- Construye m5_dataset.features_train a partir de sales_long + calendar + sell_prices
--
-- Grain: una fila por (item_id, store_id, date), igual que sales_long.
-- Consumidor: unicamente LightGBM Quantile (Fase 4c). ARIMA clasico y BQML
-- ARIMA_PLUS trabajan directo sobre sales_long (serie univariada) y no
-- consumen esta tabla -- por eso dejar NULLs en columnas de lag/rolling al
-- inicio de cada serie no es un problema (LightGBM los maneja nativamente).
--
-- Regla de no-leakage: toda window function sobre `sales` o `sell_price`
-- usa ROWS BETWEEN N PRECEDING AND 1 PRECEDING (nunca CURRENT ROW). Las
-- unicas excepciones son features deterministas derivadas de la fecha de la
-- fila actual (day_of_week, is_christmas, snap_active, days_since_start) y
-- las features de calendario/eventos (days_to_next_event, days_from_last_event),
-- que son conocidas de antemano (igual que cualquier feriado futuro) y no
-- leen la variable objetivo ni el precio -- por lo que no filtran informacion
-- futura del target. Aun asi, estas ultimas excluyen la fila actual al buscar
-- el evento mas cercano (ver comentario en calendar_event_distance).
--
-- Las justificaciones de cada feature se citan de INSTRUCCIONES.md, Fase 3.
-- Bloque Fourier generado por src/features/fourier_features.py -- si cambian
-- periodos/n_terms, correr ese script de nuevo en vez de editar a mano.
-- ============================================================================

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.features_train`
PARTITION BY date
CLUSTER BY item_id, store_id
AS

WITH

-- ── Constante pi (BigQuery no tiene PI() nativo; ACOS(-1) es el estandar) ──
consts AS (
  SELECT ACOS(-1) AS pi
),

-- ── Eventos de calendario, a nivel de fecha única (no por serie) ───────────
-- Los eventos aplican igual a las 30,490 series en una fecha dada, por lo
-- que se calculan una sola vez sobre `calendar` (~1,913 filas) y se hace
-- JOIN al resultado, en vez de recalcular por cada partición item+store.
calendar_events AS (
  SELECT
    date,
    wm_yr_wk,
    snap_CA,
    snap_TX,
    snap_WI,
    event_name_1,
    event_type_1,
    event_name_2,
    -- Marca la fecha solo si el dia tiene evento -- insumo para las window
    -- functions de distancia a evento mas cercano, mas abajo.
    CASE WHEN event_name_1 IS NOT NULL OR event_name_2 IS NOT NULL
         THEN date END AS event_date_marker
  FROM `mle-m5-forecast.m5_dataset.calendar`
),

calendar_event_distance AS (
  SELECT
    date,
    wm_yr_wk,
    snap_CA,
    snap_TX,
    snap_WI,

    -- is_event: flag binario, cualquier evento en event_type_1 o event_type_2
    CASE WHEN event_name_1 IS NOT NULL OR event_name_2 IS NOT NULL
         THEN 1 ELSE 0 END AS is_event,

    -- is_christmas: flag binario explicito, 25-dic -- Walmart cierra ese dia
    -- todos los anos, confirmado en el EDA: la serie agregada cae a cero
    CASE WHEN EXTRACT(MONTH FROM date) = 12 AND EXTRACT(DAY FROM date) = 25
         THEN 1 ELSE 0 END AS is_christmas,

    -- event_type recodificado: Navidad usa tipo propio 'Store_Closure' en vez
    -- de mezclarse con los 4 tipos genericos (flag + tipo propio a la vez,
    -- redundancia intencional de costo cero)
    CASE
      WHEN event_name_1 = 'Christmas' THEN 'Store_Closure'
      ELSE event_type_1
    END AS event_type,

    -- days_to_next_event / days_from_last_event: excluyen CURRENT ROW a
    -- proposito (1 FOLLOWING / 1 PRECEDING) para no contar el evento del
    -- propio dia dos veces -- eso ya lo cubren is_event / is_christmas.
    MIN(event_date_marker) OVER (
      ORDER BY date ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
    ) AS next_event_date,
    MAX(event_date_marker) OVER (
      ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS last_event_date

  FROM calendar_events
),

calendar_final AS (
  SELECT
    date,
    wm_yr_wk,
    snap_CA,
    snap_TX,
    snap_WI,
    is_event,
    is_christmas,
    event_type,
    DATE_DIFF(next_event_date, date, DAY) AS days_to_next_event,
    DATE_DIFF(date, last_event_date, DAY) AS days_from_last_event
  FROM calendar_event_distance
),

-- ── Base: ventas + atributos de calendario + precio semanal ────────────────
base AS (
  SELECT
    sl.item_id,
    sl.store_id,
    sl.date,
    sl.sales,
    cf.is_event,
    cf.is_christmas,
    cf.event_type,
    cf.days_to_next_event,
    cf.days_from_last_event,

    -- snap_active: SNAP no viene a nivel tienda en `calendar` (viene por
    -- estado: snap_CA/TX/WI). Se deriva el estado desde el prefijo de
    -- store_id y se selecciona la columna correspondiente.
    CASE
      WHEN sl.store_id LIKE 'CA%' THEN cf.snap_CA
      WHEN sl.store_id LIKE 'TX%' THEN cf.snap_TX
      WHEN sl.store_id LIKE 'WI%' THEN cf.snap_WI
    END AS snap_active,

    -- precio actual (sell_price, join por item_id + store_id + wm_yr_wk)
    sp.sell_price

  FROM `mle-m5-forecast.m5_dataset.sales_long` sl
  LEFT JOIN calendar_final cf
    ON sl.date = cf.date
  LEFT JOIN `mle-m5-forecast.m5_dataset.sell_prices` sp
    ON sl.item_id = sp.item_id
   AND sl.store_id = sp.store_id
   AND cf.wm_yr_wk = sp.wm_yr_wk
),

-- ── Features temporales (ventas) ────────────────────────────────────────────
temporal AS (
  SELECT
    item_id,
    store_id,
    date,
    sales,
    is_event,
    is_christmas,
    event_type,
    days_to_next_event,
    days_from_last_event,
    snap_active,
    sell_price,

    -- lag_7/14/28/182: ventas de hace N dias
    LAG(sales, 7)   OVER (PARTITION BY item_id, store_id ORDER BY date) AS lag_7,
    LAG(sales, 14)  OVER (PARTITION BY item_id, store_id ORDER BY date) AS lag_14,
    LAG(sales, 28)  OVER (PARTITION BY item_id, store_id ORDER BY date) AS lag_28,
    LAG(sales, 182) OVER (PARTITION BY item_id, store_id ORDER BY date) AS lag_182,

    -- roll_mean_7/28: promedio movil -- roll_std_28: volatilidad
    AVG(sales) OVER (
      PARTITION BY item_id, store_id ORDER BY date
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS roll_mean_7,
    AVG(sales) OVER (
      PARTITION BY item_id, store_id ORDER BY date
      ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS roll_mean_28,
    STDDEV(sales) OVER (
      PARTITION BY item_id, store_id ORDER BY date
      ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS roll_std_28,

    -- dia de semana, dia del mes, mes, ano, semana del ano -- atributos
    -- deterministas de la fecha de la fila actual, no leen sales/precio
    EXTRACT(DAYOFWEEK FROM date) AS day_of_week,
    EXTRACT(DAY FROM date)       AS day_of_month,
    EXTRACT(MONTH FROM date)     AS month,
    EXTRACT(YEAR FROM date)      AS year,
    EXTRACT(WEEK FROM date)      AS week_of_year,

    -- days_since_start: dia 1, 2, 3... desde 2011-01-29 -- proxy de
    -- tendencia continua, mas fino que "ano" categorico; justificado por la
    -- tendencia +57% vista en el EDA
    DATE_DIFF(date, DATE('2011-01-29'), DAY) AS days_since_start,

    -- days_since_last_sale: dias desde la ultima venta > 0, estrictamente
    -- anterior a la fila actual (UNBOUNDED PRECEDING AND 1 PRECEDING)
    DATE_DIFF(
      date,
      MAX(CASE WHEN sales > 0 THEN date END) OVER (
        PARTITION BY item_id, store_id ORDER BY date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
      ),
      DAY
    ) AS days_since_last_sale,

    -- pct_zeros_28d: % de ceros en los ultimos 28 dias. days_since_last_sale
    -- y pct_zeros_28d estan justificados por el hallazgo del EDA de que
    -- 78.4% de las series tienen >=50% de dias en cero; roll_mean/std no
    -- distingue patrones de intermitencia distintos con la misma media
    AVG(CASE WHEN sales = 0 THEN 1.0 ELSE 0.0 END) OVER (
      PARTITION BY item_id, store_id ORDER BY date
      ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS pct_zeros_28d

  FROM base
),

-- ── Features Fourier (estacionalidad) ───────────────────────────────────────
-- Bloque generado por src/features/fourier_features.py. Time index =
-- days_since_start: contador de dia calendario global (mismo valor para
-- todas las series en una fecha dada), no un indice por serie -- asi la
-- fase de seno/coseno queda anclada al calendario real y no se desalinea
-- entre series con distinta fecha de primera venta.
--
-- NO se agrega Fourier mensual: para LightGBM (arboles, splits arbitrarios)
-- es redundante con day_of_month, que ya captura el mismo patron sin
-- necesitar representacion suavizada. Fourier semestral si se agrega porque
-- complementa a lag_182 con la posicion ciclica dentro del semestre, en vez
-- de duplicar solo el valor puntual historico.
fourier AS (
  SELECT
    t.*,

    -- Fourier week (period=7, n_terms=3)
    SIN(2 * c.pi * 1 * t.days_since_start / 7) AS fourier_week_sin_1,
    COS(2 * c.pi * 1 * t.days_since_start / 7) AS fourier_week_cos_1,
    SIN(2 * c.pi * 2 * t.days_since_start / 7) AS fourier_week_sin_2,
    COS(2 * c.pi * 2 * t.days_since_start / 7) AS fourier_week_cos_2,
    SIN(2 * c.pi * 3 * t.days_since_start / 7) AS fourier_week_sin_3,
    COS(2 * c.pi * 3 * t.days_since_start / 7) AS fourier_week_cos_3,

    -- Fourier semester (period=182.625, n_terms=3)
    SIN(2 * c.pi * 1 * t.days_since_start / 182.625) AS fourier_semester_sin_1,
    COS(2 * c.pi * 1 * t.days_since_start / 182.625) AS fourier_semester_cos_1,
    SIN(2 * c.pi * 2 * t.days_since_start / 182.625) AS fourier_semester_sin_2,
    COS(2 * c.pi * 2 * t.days_since_start / 182.625) AS fourier_semester_cos_2,
    SIN(2 * c.pi * 3 * t.days_since_start / 182.625) AS fourier_semester_sin_3,
    COS(2 * c.pi * 3 * t.days_since_start / 182.625) AS fourier_semester_cos_3,

    -- Fourier year (period=365.25, n_terms=5)
    SIN(2 * c.pi * 1 * t.days_since_start / 365.25) AS fourier_year_sin_1,
    COS(2 * c.pi * 1 * t.days_since_start / 365.25) AS fourier_year_cos_1,
    SIN(2 * c.pi * 2 * t.days_since_start / 365.25) AS fourier_year_sin_2,
    COS(2 * c.pi * 2 * t.days_since_start / 365.25) AS fourier_year_cos_2,
    SIN(2 * c.pi * 3 * t.days_since_start / 365.25) AS fourier_year_sin_3,
    COS(2 * c.pi * 3 * t.days_since_start / 365.25) AS fourier_year_cos_3,
    SIN(2 * c.pi * 4 * t.days_since_start / 365.25) AS fourier_year_sin_4,
    COS(2 * c.pi * 4 * t.days_since_start / 365.25) AS fourier_year_cos_4,
    SIN(2 * c.pi * 5 * t.days_since_start / 365.25) AS fourier_year_sin_5,
    COS(2 * c.pi * 5 * t.days_since_start / 365.25) AS fourier_year_cos_5

  FROM temporal t
  CROSS JOIN consts c
),

-- ── Features de precio ──────────────────────────────────────────────────────
-- LAGs de precio calculados una sola vez aqui y reutilizados abajo, para no
-- recalcular la misma window function dos veces (momentum y lag_price_28
-- comparten el mismo LAG(sell_price, 28)).
price_lags AS (
  SELECT
    f.*,
    LAG(f.sell_price, 1)  OVER (PARTITION BY f.item_id, f.store_id ORDER BY f.date) AS prev_day_price,
    LAG(f.sell_price, 28) OVER (PARTITION BY f.item_id, f.store_id ORDER BY f.date) AS lag_price_28,
    -- price_rel_mean usa media movil de 365 dias, NO expandida -- una media
    -- de todo el historial arrastraria el sesgo de precios de 2011, igual
    -- que discutimos para window_size; consistente con la ventana de 365
    -- dias fijada en Fase 5
    AVG(f.sell_price) OVER (
      PARTITION BY f.item_id, f.store_id ORDER BY f.date
      ROWS BETWEEN 365 PRECEDING AND 1 PRECEDING
    ) AS price_moving_avg_365
  FROM fourier f
),

price AS (
  SELECT
    * EXCEPT (prev_day_price, price_moving_avg_365, lag_price_28),

    -- price_rel_mean: precio actual / media movil de 365 dias del item
    SAFE_DIVIDE(sell_price, price_moving_avg_365) AS price_rel_mean,

    -- price_momentum_4w: variacion % vs precio de hace 4 semanas (28 dias)
    SAFE_DIVIDE(sell_price - lag_price_28, lag_price_28) AS price_momentum_4w,

    -- lag_price_28: precio de hace 28 dias -- no lag_price_7 porque
    -- sell_price cambia a nivel semanal (wm_yr_wk), un lag de 7 dias
    -- repetiria casi siempre el mismo valor
    lag_price_28,

    -- price_changed: flag binario, cambio el precio respecto al dia
    -- anterior -- mas informativo que un lag continuo para detectar
    -- promociones puntuales
    CASE
      WHEN prev_day_price IS NULL OR sell_price IS NULL THEN NULL
      WHEN sell_price != prev_day_price THEN 1
      ELSE 0
    END AS price_changed

  FROM price_lags
)

SELECT *
FROM price
ORDER BY item_id, store_id, date;
