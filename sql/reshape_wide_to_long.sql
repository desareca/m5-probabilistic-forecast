-- Reshape M5 sales from wide to long format
-- Input: mle-m5-forecast.m5_dataset.sales_wide (30,490 rows × 1,919 columns)
-- Output: mle-m5-forecast.m5_dataset.sales_long (~59M rows)
-- Uses CROSS JOIN with generated sequences to extract all day columns

CREATE OR REPLACE TABLE `mle-m5-forecast.m5_dataset.sales_long` AS
WITH parsed_ids AS (
  SELECT
    id,
    REGEXP_SUBSTR(id, r'^[^_]+') as item_id,
    REGEXP_SUBSTR(id, r'[^_]+$') as store_id,
    t
  FROM `mle-m5-forecast.m5_dataset.sales_wide` t
),
day_numbers AS (
  SELECT num as day_num, CONCAT('d_', CAST(num AS STRING)) as day_col
  FROM UNNEST(GENERATE_ARRAY(1, 1941)) AS num
),
unnested_days AS (
  SELECT
    parsed_ids.id,
    parsed_ids.item_id,
    parsed_ids.store_id,
    day_num,
    day_col,
    SAFE.FLOAT64(JSON_EXTRACT_SCALAR(TO_JSON_STRING(parsed_ids.t), CONCAT('$.', day_col))) as sales
  FROM parsed_ids
  CROSS JOIN day_numbers
)
SELECT
  id,
  item_id,
  store_id,
  DATE_ADD(DATE('2011-01-29'), INTERVAL day_num - 1 DAY) as date,
  CAST(sales AS INT64) as sales
FROM unnested_days
WHERE sales IS NOT NULL
ORDER BY item_id, store_id, date;
