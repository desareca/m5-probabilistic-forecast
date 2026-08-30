"""
Construye las 3 tablas agregadas para Looker Studio -- Fase 8.

sql/aggregations/agg_predictions.sql, agg_metrics.sql,
agg_weekly_comparison.sql -- ver cada archivo para el detalle de fuentes y
decisiones. Este script solo ejecuta los 3 DDLs y reporta filas/costo,
igual patron que run_ddl() en src/evaluation/build_case_analysis.py.

Uso:
    python -m sql.aggregations.build_aggregations
"""

import logging

from src.common import DATASET, PROJECT, get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TABLES = ["agg_predictions", "agg_metrics", "agg_weekly_comparison"]


def run_ddl(client, sql_path: str, table_name: str) -> None:
    with open(sql_path) as f:
        sql = f.read()

    job = client.query(sql)
    job.result()
    gb = (job.total_bytes_billed or 0) / 1e9
    dest = client.get_table(f"{PROJECT}.{DATASET}.{table_name}")
    logger.info(
        f"{table_name}: OK -- {dest.num_rows} filas, {gb:.3f} GB facturados (~${gb / 1024 * 6.25:.4f})"
    )


def main() -> None:
    client = get_bq_client()
    for table_name in TABLES:
        run_ddl(client, f"sql/aggregations/{table_name}.sql", table_name)
    logger.info("Fase 8 completa -- 3 tablas agregadas listas para Looker Studio.")


if __name__ == "__main__":
    main()
