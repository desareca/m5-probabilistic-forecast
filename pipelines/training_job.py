"""
Custom Training Job de Vertex AI -- Fase 7, Tarea 1/2.

Version "de produccion" de src/models/lgbm_quantile.py: mismo entrenamiento
(5 modelos independientes, uno por percentil, sobre m5_dataset.lgbm_sample),
pero como script empaquetable en Docker en vez de smoke test local --
recibe la ventana temporal y el destino de artefactos como argumentos de
linea de comandos (skill-vertex-ai.md: "recibir hiperparametros como
argumentos, guardar artefactos en GCS al terminar"), no hardcodeados.

No reimplementa la logica de fetch/cast/train/predict -- la importa de
src.models.lgbm_quantile, que ya la tiene probada desde Fase 4c/5. Este
script es una capa fina de orquestacion: parsea args, resuelve la ventana
de fechas, llama a esa logica, y sube modelos + metricas a GCS en vez de
dejarlos en el filesystem local del contenedor (que se destruye al
terminar el job -- ver skill-vertex-ai.md, "Artefactos siempre en GCS").

Uso local (fuera de Vertex AI, para probar el empaquetado):
    python -m pipelines.training_job \
        --train-start 2015-05-24 --val-start 2016-05-24 --val-end 2016-06-19 \
        --output-gcs-path gs://mle-m5-forecast-m5-bucket/models/manual-test

Dentro de un Custom Training Job, Vertex AI expone la ruta de salida
asignada via la variable de entorno AIP_MODEL_DIR -- si --output-gcs-path
no se pasa explicitamente, el script cae a esa variable (ver
skill-vertex-ai.md: "credenciales/paths automaticos dentro de Vertex AI").
"""

import argparse
import json
import logging
import os
import tempfile

from google.cloud import bigquery, storage

from src.evaluation.metrics import pinball_loss
from src.models.lgbm_quantile import (
    DATASET,
    PROJECT,
    QUANTILE_LEVELS,
    cast_categoricals,
    get_reduced_memory_dtypes,
    _fetch_features_window,
    predict_quantiles,
    train_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena LightGBM Quantile para Vertex AI Custom Training.")
    parser.add_argument("--train-start", required=True, help="YYYY-MM-DD, inicio de la ventana TRAIN.")
    parser.add_argument("--val-start", required=True, help="YYYY-MM-DD, inicio de la ventana VAL.")
    parser.add_argument("--val-end", required=True, help="YYYY-MM-DD, fin (inclusive) de la ventana VAL.")
    parser.add_argument(
        "--output-gcs-path",
        default=os.environ.get("AIP_MODEL_DIR"),
        help="gs://.../ donde subir modelos + metricas. Default: AIP_MODEL_DIR (inyectado por Vertex AI).",
    )
    args = parser.parse_args()
    if not args.output_gcs_path:
        parser.error("--output-gcs-path es obligatorio si AIP_MODEL_DIR no esta seteado en el entorno.")
    return args


def upload_dir_to_gcs(local_dir: str, gcs_path: str) -> None:
    """Sube todo el contenido de local_dir (modelos .txt + metrics.json) a
    gcs_path, preservando nombres de archivo. gcs_path debe empezar con
    gs://. No usa gsutil (no garantizado en la imagen base) -- solo el
    cliente de google-cloud-storage, ya en requirements-training.txt."""
    assert gcs_path.startswith("gs://"), f"--output-gcs-path debe empezar con gs://, recibido: {gcs_path}"
    bucket_name, _, prefix = gcs_path[len("gs://"):].partition("/")

    client = storage.Client(project=PROJECT)
    bucket = client.bucket(bucket_name)

    for filename in os.listdir(local_dir):
        local_path = os.path.join(local_dir, filename)
        blob_path = f"{prefix.rstrip('/')}/{filename}" if prefix else filename
        bucket.blob(blob_path).upload_from_filename(local_path)
        logger.info(f"  -> gs://{bucket_name}/{blob_path}")


def compute_val_metrics(predictions_df, val_df) -> dict[str, float]:
    """Pinball Loss promedio por percentil sobre la ventana VAL de este
    run -- las metricas que Model Registry etiquetara (Tarea 2) y que
    evaluate_component comparara contra el baseline (Tarea 3)."""
    merged = predictions_df.merge(
        val_df[["item_id", "store_id", "date", "sales"]], on=["item_id", "store_id", "date"], how="inner"
    )
    metrics = {}
    for q_name, alpha in QUANTILE_LEVELS.items():
        # pinball_loss() retorna el array por observacion, sin promediar
        # (ver src/evaluation/metrics.py) -- np.mean() agrega aca.
        losses = pinball_loss(merged["sales"].to_numpy(), merged[q_name].to_numpy(), alpha)
        metrics[q_name] = float(losses.mean())
    metrics["avg"] = float(sum(metrics.values()) / len(metrics))
    return metrics


def run(train_start: str, val_start: str, val_end: str, output_gcs_path: str) -> None:
    import pandas as pd

    client = bigquery.Client(project=PROJECT)
    dtypes = get_reduced_memory_dtypes(client)

    train_start_ts = pd.Timestamp(train_start)
    val_start_ts = pd.Timestamp(val_start)
    val_end_ts = pd.Timestamp(val_end)

    with tempfile.TemporaryDirectory() as model_dir:
        train_df = _fetch_features_window(
            client, train_start_ts, val_start_ts, dtypes, label="train", exclude_id_cols=True
        )
        train_df = cast_categoricals(train_df)
        boosters = train_models(train_df, model_dir=model_dir)
        del train_df

        val_df = _fetch_features_window(
            client, val_start_ts, val_end_ts + pd.Timedelta(days=1), dtypes, label="val", exclude_id_cols=False
        )
        val_df = cast_categoricals(val_df)
        predictions_df = predict_quantiles(boosters, val_df)

        metrics = compute_val_metrics(predictions_df, val_df)
        logger.info("Metricas VAL (Pinball Loss por percentil):\n%s", json.dumps(metrics, indent=2))

        metrics_path = os.path.join(model_dir, "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(
                {
                    "train_start": train_start,
                    "val_start": val_start,
                    "val_end": val_end,
                    "pinball_loss": metrics,
                },
                f,
                indent=2,
            )

        upload_dir_to_gcs(model_dir, output_gcs_path)

    logger.info(f"Training job completo. Artefactos en {output_gcs_path}")


def main() -> None:
    args = parse_args()
    run(args.train_start, args.val_start, args.val_end, args.output_gcs_path)


if __name__ == "__main__":
    main()
