"""
Batch Prediction sobre el test set real -- Fase 7, Tarea 4 (pasos c y d).

Carga los 5 modelos LightGBM (.txt) del run ya registrado en Model
Registry (Tarea 2) directo desde GCS -- NO usa el mecanismo nativo de
Vertex AI Batch Prediction Job: el Model registrado no tiene un serving
container funcional (ver pipelines/submit_training_job.py,
register_model() -- serving_container_image_uri apunta a la imagen de
training solo para satisfacer el campo obligatorio, no implementa el
contrato HTTP de prediccion de Vertex AI).

Corre LOCAL (Workstation), no como Custom Job de Vertex AI: features_test
son 853,720 filas -- un orden de magnitud mas chico que el TRAIN de ~1.1M
que motivo el CustomJob en Tarea 2, y esto es solo inferencia (Booster.
predict(), sin Dataset.construct() ni entrenamiento) -- no hay riesgo de
OOM que justifique la ceremonia de un CustomJob nuevo aca.

Reutiliza predict_quantiles/cast_categoricals/get_reduced_memory_dtypes de
src.models.lgbm_quantile -- MISMO preprocesamiento que Tarea 2, para que
las predicciones de test sean comparables (nada nuevo introducido solo
para test).

Esta es la UNICA vez en todo el proyecto que se compara contra el test set
real (test_labels) -- el Pinball Loss aca es la metrica final honesta, no
una estimacion de walk-forward CV.

Uso:
    python -m pipelines.batch_predict --model-gcs-dir gs://.../model
"""

import argparse
import json
import logging
import os
import tempfile

import lightgbm as lgb
import pandas as pd
from google.cloud import bigquery, storage

from src.common import DATASET, PROJECT, QUANTILE_LEVELS, write_to_bigquery
from src.evaluation.metrics import pinball_loss
from src.models.lgbm_quantile import cast_categoricals, get_reduced_memory_dtypes, predict_quantiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FEATURES_TEST_TABLE = f"{PROJECT}.{DATASET}.features_test"
TEST_LABELS_TABLE = f"{PROJECT}.{DATASET}.test_labels"
PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.predictions_test"
METRICS_TABLE = f"{PROJECT}.{DATASET}.test_evaluation_metrics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-gcs-dir", required=True, help="gs://.../model -- carpeta con lgbm_p*.txt (Tarea 2)")
    return parser.parse_args()


def download_boosters(model_gcs_dir: str, local_dir: str) -> dict[str, lgb.Booster]:
    assert model_gcs_dir.startswith("gs://")
    bucket_name, _, prefix = model_gcs_dir[len("gs://"):].partition("/")
    client = storage.Client(project=PROJECT)
    bucket = client.bucket(bucket_name)

    boosters = {}
    for q_name in QUANTILE_LEVELS:
        blob_path = f"{prefix.rstrip('/')}/lgbm_{q_name}.txt"
        local_path = os.path.join(local_dir, f"lgbm_{q_name}.txt")
        bucket.blob(blob_path).download_to_filename(local_path)
        boosters[q_name] = lgb.Booster(model_file=local_path)
        logger.info(f"  -> cargado {q_name} desde gs://{bucket_name}/{blob_path}")
    return boosters


def fetch_features_test(client: bigquery.Client) -> pd.DataFrame:
    dtypes = get_reduced_memory_dtypes(client)
    df = client.query(f"SELECT * FROM `{FEATURES_TEST_TABLE}`").to_dataframe(dtypes=dtypes)
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"features_test: {len(df)} filas")
    return df


def evaluate(predictions_df: pd.DataFrame, client: bigquery.Client) -> dict[str, float]:
    """test_labels es la fuente de verdad para el ground truth, aunque
    features_test tambien traiga la columna sales embebida (por construccion,
    igual que features_train -- ver build_features_train.sql) -- nunca se
    usa esa copia como input del modelo (excluida en EXCLUDE_COLS de
    predict_quantiles), pero para evaluar se hace un merge explicito
    contra test_labels de todas formas, no contra la columna embebida:
    mantiene la evaluacion trazable a una unica fuente de verdad auditable."""
    labels_df = client.query(
        f"SELECT item_id, store_id, date, sales FROM `{TEST_LABELS_TABLE}`"
    ).to_dataframe()
    labels_df["date"] = pd.to_datetime(labels_df["date"])

    merged = predictions_df.merge(labels_df, on=["item_id", "store_id", "date"], how="inner")
    if len(merged) != len(predictions_df):
        raise RuntimeError(
            f"Merge con test_labels perdio filas: {len(predictions_df)} predicciones vs "
            f"{len(merged)} matcheadas -- revisar join keys, sin fallback silencioso."
        )

    metrics = {}
    for q_name, alpha in QUANTILE_LEVELS.items():
        losses = pinball_loss(merged["sales"].to_numpy(), merged[q_name].to_numpy(), alpha)
        metrics[q_name] = float(losses.mean())
    metrics["avg"] = float(sum(metrics.values()) / len(metrics))
    return metrics


def main() -> None:
    args = parse_args()
    client = bigquery.Client(project=PROJECT)

    with tempfile.TemporaryDirectory() as tmp:
        logger.info(f"Descargando modelos desde {args.model_gcs_dir}...")
        boosters = download_boosters(args.model_gcs_dir, tmp)

        features_df = fetch_features_test(client)
        features_df = cast_categoricals(features_df)
        predictions_df = predict_quantiles(boosters, features_df)

    schema = [
        bigquery.SchemaField("item_id", "STRING"),
        bigquery.SchemaField("store_id", "STRING"),
        bigquery.SchemaField("date", "DATE"),
        bigquery.SchemaField("p05", "FLOAT"),
        bigquery.SchemaField("p25", "FLOAT"),
        bigquery.SchemaField("p50", "FLOAT"),
        bigquery.SchemaField("p75", "FLOAT"),
        bigquery.SchemaField("p95", "FLOAT"),
    ]
    write_to_bigquery(client, predictions_df, PREDICTIONS_TABLE, schema)

    metrics = evaluate(predictions_df, client)
    logger.info("=== Pinball Loss sobre TEST SET REAL (nunca visto hasta ahora en todo el proyecto) ===")
    logger.info(json.dumps(metrics, indent=2))

    metrics_df = pd.DataFrame(
        [{"quantile_name": k, "pinball_loss": v, "model_gcs_dir": args.model_gcs_dir} for k, v in metrics.items()]
    )
    metrics_schema = [
        bigquery.SchemaField("quantile_name", "STRING"),
        bigquery.SchemaField("pinball_loss", "FLOAT"),
        bigquery.SchemaField("model_gcs_dir", "STRING"),
    ]
    write_to_bigquery(client, metrics_df, METRICS_TABLE, metrics_schema)
    logger.info(f"Metricas escritas en {METRICS_TABLE}")


if __name__ == "__main__":
    main()
