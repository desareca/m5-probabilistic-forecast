"""
Helpers de escritura compartidos por los 3 scripts de walk-forward CV
(arima_cv.py, bqml_arima_cv.py, lgbm_cv.py) -- Fase 5.

Patron comun: cada modelo escribe sus predicciones/metadata de CV en una
tabla con columna fold_id, poblada fold por fold (no de una sola vez al
final) para no perder progreso si un fold falla a mitad de camino -- BQML
en particular tiene jobs que cuestan dinero real, asi que reintentar todo
desde cero por un fallo en el ultimo fold no es aceptable.

Idempotencia: antes de insertar un fold, se borran sus filas previas
(delete_existing_fold_rows). Permite re-correr un fold individual (o el
walk-forward completo) sin duplicar filas ni tener que hacer DROP TABLE
manual.
"""

import logging

import pandas as pd
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

logger = logging.getLogger(__name__)


def delete_existing_fold_rows(client: bigquery.Client, table: str, fold_id: int) -> None:
    try:
        client.get_table(table)
    except NotFound:
        logger.info(f"  {table} no existe aun -- se creara en el primer INSERT.")
        return

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("fold_id", "INTEGER", fold_id)]
    )
    job = client.query(f"DELETE FROM `{table}` WHERE fold_id = @fold_id", job_config=job_config)
    job.result()
    logger.info(f"  {table}: filas previas de fold {fold_id} eliminadas ({job.num_dml_affected_rows or 0})")


def append_df(client: bigquery.Client, df: pd.DataFrame, table: str, schema: list) -> None:
    if df.empty:
        # load_table_from_dataframe con 0 filas puede fallar a crear el
        # schema correctamente en tablas nuevas -- y de cualquier forma no
        # hay nada que insertar. delete_existing_fold_rows ya se encargo de
        # limpiar cualquier fila vieja de este fold, asi que no insertar
        # nada es el resultado correcto (ej. un fold de ARIMA donde las 32
        # series fallaron converger).
        logger.warning(f"  {table}: DataFrame vacio -- no se inserta nada.")
        return

    job_config = bigquery.LoadJobConfig(
        schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )
    load_job = client.load_table_from_dataframe(df, table, job_config=job_config)
    load_job.result()
    logger.info(f"  {table}: {len(df)} filas insertadas (fold {df['fold_id'].iloc[0]})")


def write_fold(client: bigquery.Client, df: pd.DataFrame, table: str, schema: list, fold_id: int) -> None:
    """Combina delete + append -- punto de entrada unico que usan los 3 scripts."""
    delete_existing_fold_rows(client, table, fold_id)
    append_df(client, df, table, schema)
