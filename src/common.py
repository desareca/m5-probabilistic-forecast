"""
Constantes y helpers de BigQuery compartidos entre los 3 modelos --
extraido de src/models/arima_baseline.py (Fase 7, Tarea 2).

Motivo: pipelines/training_job.py (el script que corre DENTRO del
container Docker de Vertex AI, requirements-training.txt minimalista, sin
pmdarima/statsmodels) importa src.models.lgbm_quantile, que a su vez
importaba estas constantes desde src.models.arima_baseline -- y ese modulo
carga pmdarima/statsmodels a nivel de import, aunque training_job.py nunca
los usa. Resultado: el CustomJob fallaba con ModuleNotFoundError apenas
arrancaba (exit code 1), porque el import en cadena arrastraba
dependencias de ARIMA que nunca se instalaron en la imagen.

arima_baseline.py sigue exponiendo estos mismos nombres (re-exportados,
ver import al inicio de ese archivo) para no romper a arima_cv.py,
build_case_analysis.py, etc. -- ese modulo SI corre siempre con el venv
completo (Workstation), asi que no hay problema en que siga cargando
pmdarima/statsmodels ademas de esto.
"""

import logging

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

QUANTILE_LEVELS = {"p05": 0.05, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p95": 0.95}


def get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


def write_to_bigquery(client: bigquery.Client, df: pd.DataFrame, table: str, schema: list[bigquery.SchemaField]) -> None:
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    load_job = client.load_table_from_dataframe(df, table, job_config=job_config)
    load_job.result()
    logger.info(f"Escritas {len(df)} filas en {table}")
