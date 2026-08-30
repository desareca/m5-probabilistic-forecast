"""
Features para el test set real -- Fase 7, Tarea 4 (paso b).

Reutiliza sql/build_features_train.sql TAL CUAL via sustitucion de texto
con anclas explicitas (falla fuerte si alguna no matchea exactamente una
vez -- ninguna reescritura silenciosa), en vez de mantener una segunda
copia de ~300 lineas que podria divergir con el tiempo. Dos cambios:

1. La fuente `sales_long` se reemplaza por UNION ALL de sales_long +
   test_labels -- asi los lags/rolling (LAG, AVG/STDDEV con ROWS BETWEEN N
   PRECEDING AND 1 PRECEDING) ven la historia real inmediatamente anterior
   a cada fecha de test, sin gap. Esto NO introduce leakage nuevo: cada
   fila sigue mirando estrictamente hacia atras desde su propia fecha,
   igual que features_train (ver cabecera de ese archivo) -- test_labels
   solo aporta historia pasada real para las fechas de test, nunca futuro
   relativo a la fila que se esta features-eando.
2. El destino pasa a `features_test`, y el SELECT final se filtra a
   date >= test_start (calculado dinamicamente desde MIN(date) de
   test_labels, nunca hardcodeado) -- no hace falta recalcular features
   para el historial viejo, eso ya esta en features_train.

calendar y sell_prices ya cubren las fechas de test sin ingesta adicional
(calendar tiene 1,969 filas desde Fase 2, sell_prices no esta bloqueado
-- los precios se conocen de antemano).

Uso:
    python -m src.features.build_features_test
"""

import logging

from google.cloud import bigquery

from src.common import DATASET, PROJECT, get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SQL_PATH = "sql/build_features_train.sql"
SALES_LONG_TABLE = f"{PROJECT}.{DATASET}.sales_long"
TEST_LABELS_TABLE = f"{PROJECT}.{DATASET}.test_labels"
DEST_TABLE = f"{PROJECT}.{DATASET}.features_test"


def build_query() -> str:
    with open(SQL_PATH) as f:
        sql = f.read()

    old_create = f"CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.features_train`"
    new_create = f"CREATE OR REPLACE TABLE `{DEST_TABLE}`"
    assert sql.count(old_create) == 1, f"Ancla de CREATE TABLE no encontrada exactamente 1 vez en {SQL_PATH}"
    sql = sql.replace(old_create, new_create)

    old_source = f"FROM `{SALES_LONG_TABLE}` sl"
    new_source = f"""FROM (
    SELECT item_id, store_id, date, sales FROM `{SALES_LONG_TABLE}`
    UNION ALL
    SELECT item_id, store_id, date, sales FROM `{TEST_LABELS_TABLE}`
  ) sl"""
    assert sql.count(old_source) == 1, f"Ancla de FROM sales_long no encontrada exactamente 1 vez en {SQL_PATH}"
    sql = sql.replace(old_source, new_source)

    old_final = "SELECT *\nFROM price;"
    new_final = "SELECT *\nFROM price\nWHERE date >= @test_start;"
    assert sql.count(old_final) == 1, f"Ancla de SELECT final no encontrada exactamente 1 vez en {SQL_PATH}"
    sql = sql.replace(old_final, new_final)

    return sql


def get_test_start(client: bigquery.Client) -> str:
    row = client.query(f"SELECT MIN(date) AS test_start FROM `{TEST_LABELS_TABLE}`").result()
    test_start = list(row)[0]["test_start"]
    logger.info(f"test_start = {test_start}")
    return str(test_start)


def main() -> None:
    client = get_bq_client()
    test_start = get_test_start(client)

    sql = build_query()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("test_start", "DATE", test_start)]
    )

    logger.info(f"Construyendo {DEST_TABLE} (fuente: sales_long UNION ALL test_labels, filtrado a date >= {test_start})...")
    job = client.query(sql, job_config=job_config)
    job.result()
    gb = (job.total_bytes_billed or 0) / 1e9
    logger.info(f"Query OK -- {gb:.3f} GB facturados (~${gb / 1024 * 6.25:.4f})")

    dest = client.get_table(DEST_TABLE)
    logger.info(f"{DEST_TABLE}: {dest.num_rows} filas")

    expected = client.query(f"SELECT COUNT(*) AS n FROM `{TEST_LABELS_TABLE}`").result()
    expected_n = list(expected)[0]["n"]
    if dest.num_rows != expected_n:
        raise RuntimeError(
            f"features_test tiene {dest.num_rows} filas pero test_labels tiene {expected_n} -- "
            f"deberian coincidir exacto (LEFT JOINs preservan todas las filas base). Revisar el filtro date >= test_start."
        )
    logger.info("Row count verificado contra test_labels -- coincide exacto.")


if __name__ == "__main__":
    main()
