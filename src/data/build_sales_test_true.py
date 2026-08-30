"""
Ingesta del test set real de M5 -- Fase 7, Tarea 4 (Batch Prediction).

`sales_long` se construyo unicamente desde sales_train_validation.csv
(1,913 dias, termina en 2016-04-24 -- coincide con el fold 5 de
src/evaluation/folds.py). El verdadero test set de M5 -- ventas reales
nunca miradas -- vive en sales_train_evaluation.csv, que Fase 2 YA SUBIO A
GCS mismo (gs://.../raw/sales_train_evaluation.csv) pero deliberadamente
NUNCA CARGO A BIGQUERY, para que el test set estuviera bloqueado
fisicamente y no solo por disciplina de codigo -- ver
phase-summaries/02-datos-eda.md, "Decision de Diseño". Ese mismo documento
ya nombraba el destino de esta tabla `test_labels`, reusado aca tal cual.

Este script:
1. Carga sales_train_evaluation.csv DESDE el objeto GCS que ya existe (no
   hace falta descargar de Kaggle de nuevo ni volver a subir el CSV) a
   BigQuery como `sales_evaluation_wide`.
2. Reshape wide -> long SOLO de los dias posteriores al MAX(date) actual
   de sales_long (calculado dinamicamente, nunca hardcodeado -- mismo
   principio que src/evaluation/folds.py).
3. Escribe `test_labels` -- tabla nueva, nunca se mezcla con sales_long.

Parseo de item_id/store_id: identico a sql/reshape_wide_to_long.sql (split
por '_', item_id = tokens 0-2, store_id = tokens 3-4) -- la version
efectivamente usada para sales_long (ver commit 79c90a0, phase-summaries/
02-datos-eda.md: el bug original de regex daba solo 3 series en vez de
30,490). NO la variante con REGEXP_SUBSTR de sql/reshape_wide_to_long.py.

Uso:
    python -m src.data.build_sales_test_true
"""

import logging

from google.cloud import bigquery

from src.common import DATASET, PROJECT, get_bq_client
from src.data.load_to_bq import BUCKET_NAME, load_csv_to_bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SALES_LONG_TABLE = f"{PROJECT}.{DATASET}.sales_long"
WIDE_TABLE = f"{PROJECT}.{DATASET}.sales_evaluation_wide"
DEST_TABLE = f"{PROJECT}.{DATASET}.test_labels"
GCS_URI = f"gs://{BUCKET_NAME}/raw/sales_train_evaluation.csv"
START_DATE = "2011-01-29"  # d_1 -- identico a sql/reshape_wide_to_long.sql


def get_current_max_day_num(client: bigquery.Client) -> int:
    """Dia (1-indexado desde START_DATE) del ultimo dato real en
    sales_long. Los dias de sales_evaluation_wide posteriores a este son
    el test set nunca visto."""
    query = f"SELECT MAX(date) AS max_date FROM `{SALES_LONG_TABLE}`"
    max_date = client.query(query).to_dataframe()["max_date"].iloc[0]
    query_offset = f"SELECT DATE_DIFF(DATE('{max_date}'), DATE('{START_DATE}'), DAY) + 1 AS day_num"
    day_num = int(client.query(query_offset).to_dataframe()["day_num"].iloc[0])
    logger.info(f"sales_long MAX(date) = {max_date} -> day_num = {day_num}. "
                f"Dias > {day_num} en sales_evaluation_wide son el test set real.")
    return day_num


def reshape_incremental_days(client: bigquery.Client, current_max_day_num: int) -> None:
    """Reshape wide -> long de sales_evaluation_wide, filtrado a day_num >
    current_max_day_num -- solo los dias que NO estan ya en sales_long.
    Mismo parseo de item_id/store_id y misma logica de CROSS JOIN +
    JSON_EXTRACT_SCALAR que sql/reshape_wide_to_long.sql, generalizada a
    un rango de dias dinamico via GENERATE_ARRAY en vez del literal 1941
    hardcodeado (asi funciona sin importar cuantos dias tenga en realidad
    el CSV de evaluation)."""
    table = client.get_table(WIDE_TABLE)
    day_cols = [f.name for f in table.schema if f.name.startswith("d_")]
    max_day_available = max(int(c.split("_")[1]) for c in day_cols)

    if max_day_available <= current_max_day_num:
        raise RuntimeError(
            f"sales_evaluation_wide solo tiene hasta d_{max_day_available}, pero sales_long ya "
            f"llega a day_num={current_max_day_num} -- no hay dias nuevos que extraer."
        )

    query = f"""
        CREATE OR REPLACE TABLE `{DEST_TABLE}`
        PARTITION BY date
        CLUSTER BY item_id, store_id
        AS
        WITH parsed_ids AS (
          SELECT
            id,
            CONCAT(SPLIT(id, '_')[OFFSET(0)], '_', SPLIT(id, '_')[OFFSET(1)], '_', SPLIT(id, '_')[OFFSET(2)]) AS item_id,
            CONCAT(SPLIT(id, '_')[OFFSET(3)], '_', SPLIT(id, '_')[OFFSET(4)]) AS store_id,
            t
          FROM `{WIDE_TABLE}` t
        ),
        day_numbers AS (
          SELECT num AS day_num, CONCAT('d_', CAST(num AS STRING)) AS day_col
          FROM UNNEST(GENERATE_ARRAY({current_max_day_num + 1}, {max_day_available})) AS num
        ),
        unnested_days AS (
          SELECT
            parsed_ids.item_id,
            parsed_ids.store_id,
            day_num,
            SAFE.FLOAT64(JSON_EXTRACT_SCALAR(TO_JSON_STRING(parsed_ids.t), CONCAT('$.', day_col))) AS sales
          FROM parsed_ids
          CROSS JOIN day_numbers
        )
        SELECT
          item_id,
          store_id,
          DATE_ADD(DATE('{START_DATE}'), INTERVAL day_num - 1 DAY) AS date,
          CAST(sales AS INT64) AS sales
        FROM unnested_days
        WHERE sales IS NOT NULL
    """
    job = client.query(query)
    job.result()
    dest = client.get_table(DEST_TABLE)
    n_days = max_day_available - current_max_day_num
    logger.info(f"{DEST_TABLE}: {dest.num_rows} filas ({n_days} dias x series).")


def main() -> None:
    client = get_bq_client()

    logger.info(f"Cargando {GCS_URI} (ya en GCS desde Fase 2) a {WIDE_TABLE}...")
    load_csv_to_bigquery(GCS_URI, DATASET, "sales_evaluation_wide")

    current_max_day_num = get_current_max_day_num(client)
    reshape_incremental_days(client, current_max_day_num)

    logger.info("Test set real ingerido en test_labels. Sigue bloqueado hasta el paso de evaluacion final.")


if __name__ == "__main__":
    main()
