"""
Lanza el Custom Training Job en Vertex AI (imagen de la Tarea 1) y registra
el modelo resultante en Model Registry -- Fase 7, Tarea 2.

Ventana temporal: fold 5 de walk-forward CV (el mas reciente -- ver
src/evaluation/folds.py), la misma que ya uso el smoke test de Fase 4c y
el propio walk-forward de Fase 5. Consistencia deliberada: este primer
modelo "de produccion" debe ser comparable con los resultados ya
documentados en phase-summaries/05-walk-forward-cv.md y 06-evaluacion.md,
no una ventana nueva sin referencia.

Usa aiplatform.CustomJob (no CustomContainerTrainingJob) porque este ultimo
esta pensado para entrenar Y registrar en un solo paso, lo que exige pasar
un serving_container_image_uri incluso si nunca se va a desplegar un
endpoint online (no es el caso aqui -- ver skill-vertex-ai.md). Separar
"correr el job" de "registrar el modelo" da control explicito sobre las
labels de metricas en el paso de registro.

base_output_dir activa las variables de entorno AIP_MODEL_DIR/
AIP_CHECKPOINT_DIR/AIP_TENSORBOARD_LOG_DIR dentro del contenedor
(convencion de Vertex AI: AIP_MODEL_DIR = base_output_dir + "/model/") --
pipelines/training_job.py ya cae a esa variable si no se le pasa
--output-gcs-path explicito, asi que no hace falta pasarla como argumento.

Uso (requiere venv con requirements.txt completo, no requirements-training.txt
-- este script corre fuera del container, orquestando Vertex AI):
    python -m pipelines.submit_training_job
"""

import argparse
import json
import logging
import re
from datetime import datetime, timezone

from google.cloud import aiplatform, storage

from src.evaluation.folds import get_bq_client, get_folds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
REGION = "us-central1"
BUCKET = "mle-m5-forecast-m5-bucket"
# v5: agrega google-cloud-aiplatform a requirements-training.txt para que
# la MISMA imagen sirva de base_image a los componentes livianos del KFP
# pipeline (Tarea 3) -- sin cambios en la logica de entrenamiento en si.
IMAGE_URI = f"{REGION}-docker.pkg.dev/{PROJECT}/m5-training/lgbm-quantile:v5"

MACHINE_TYPE = "n1-standard-8"  # ver skill-vertex-ai.md: CPU basta, buen balance para el tamano del M5.


def sanitize_label_value(value: str) -> str:
    """
    Las labels de Vertex AI exigen [a-z0-9_-]{0,63} -- sin puntos ni
    mayusculas. Las fechas (YYYY-MM-DD) ya cumplen tal cual; los floats de
    Pinball Loss necesitan reemplazar '.' por '_' y redondearse (4
    decimales alcanza para comparar metricas entre runs a simple vista en
    la consola de Vertex AI, sin acercarse al limite de 63 caracteres).
    """
    return re.sub(r"[^a-z0-9_-]", "_", str(value).lower())


def submit_training_job(train_start: str, val_start: str, val_end: str, run_id: str) -> str:
    """Lanza el CustomJob de forma sincrona (bloquea hasta que termine o
    falle) y retorna el base_output_dir usado -- necesario para leer
    metrics.json despues. Sync porque este script se corre a mano, no
    dentro de un pipeline (eso es la Tarea 3)."""
    base_output_dir = f"gs://{BUCKET}/models/lgbm_quantile/{run_id}"

    aiplatform.init(project=PROJECT, location=REGION, staging_bucket=f"gs://{BUCKET}/staging")

    job = aiplatform.CustomJob(
        display_name=f"lgbm-quantile-training-{run_id}",
        worker_pool_specs=[
            {
                "machine_spec": {"machine_type": MACHINE_TYPE},
                "replica_count": 1,
                "container_spec": {
                    "image_uri": IMAGE_URI,
                    "args": [
                        "--train-start", train_start,
                        "--val-start", val_start,
                        "--val-end", val_end,
                    ],
                },
            }
        ],
        base_output_dir=base_output_dir,
    )

    logger.info(f"Lanzando CustomJob (imagen {IMAGE_URI}, {MACHINE_TYPE})...")
    logger.info(f"TRAIN >= {train_start}, VAL [{val_start}, {val_end}]")
    # service_account explicito: sin esto, Vertex AI usa la cuenta de
    # Compute Engine por defecto del proyecto, no mle-m5-sa (la que tiene
    # los roles IAM de BigQuery/Storage asignados desde la Fase 1) -- el
    # job fallaria por permisos al intentar leer features_train.
    job.run(sync=True, service_account=f"mle-m5-sa@{PROJECT}.iam.gserviceaccount.com")
    logger.info(f"CustomJob completo. Artefactos en {base_output_dir}/model/")

    return f"{base_output_dir}/model"


def read_metrics(model_gcs_dir: str) -> dict:
    """Descarga metrics.json (escrito por pipelines/training_job.py) desde
    model_gcs_dir. No usa gsutil -- mismo criterio que training_job.py."""
    assert model_gcs_dir.startswith("gs://")
    bucket_name, _, prefix = model_gcs_dir[len("gs://"):].partition("/")

    client = storage.Client(project=PROJECT)
    blob = client.bucket(bucket_name).blob(f"{prefix.rstrip('/')}/metrics.json")
    metrics_raw = json.loads(blob.download_as_text())
    logger.info("metrics.json leido:\n%s", json.dumps(metrics_raw, indent=2))
    return metrics_raw


def register_model(model_gcs_dir: str, metrics_raw: dict, run_id: str) -> aiplatform.Model:
    """
    Registra el modelo en Vertex AI Model Registry -- artifact_uri apunta
    a la carpeta GCS (Fase 7 Tarea 2), labels incluyen Pinball Loss por
    percentil para comparar versiones desde la consola sin codigo (ver
    skill-vertex-ai.md).

    Confirmado en la corrida real: el SDK de aiplatform SI exige
    serving_container_image_uri para Model.upload() (ValueError explicito,
    "required if no local_model is provided") -- no existe la opcion de
    registro "solo artefacto" que se esperaba. Fix: apuntarlo a la MISMA
    imagen de training (IMAGE_URI). Esto satisface el campo obligatorio
    pero NO la vuelve deployable de verdad -- el container de la Tarea 1
    solo implementa el ENTRYPOINT de entrenamiento (pipelines/training_job.py
    con argparse), no el contrato HTTP de prediccion de Vertex AI (rutas
    /predict y /health que un servidor real como Flask/FastAPI expondria).
    Sirve para Model Registry (versionado + labels de metricas, el
    entregable real de esta tarea) pero CUALQUIER intento de desplegar un
    endpoint o correr un Batch Prediction Job nativo de Vertex AI sobre
    este Model fallara. La Tarea 4 (batch prediction) necesitara su propio
    enfoque -- probablemente un script custom que cargue los .txt de
    LightGBM directo desde GCS y prediga sobre BigQuery, no el mecanismo
    nativo de Vertex AI Batch Prediction Job (que si requeriria un serving
    container funcional). Queda marcado para resolver en esa tarea.
    """
    aiplatform.init(project=PROJECT, location=REGION)

    labels = {"run_id": sanitize_label_value(run_id)}
    for q_name, loss in metrics_raw["pinball_loss"].items():
        labels[f"pinball_{q_name}"] = sanitize_label_value(f"{loss:.4f}")

    model = aiplatform.Model.upload(
        display_name=f"lgbm-quantile-{run_id}",
        artifact_uri=model_gcs_dir,
        serving_container_image_uri=IMAGE_URI,
        labels=labels,
        description=(
            f"LightGBM Quantile, TRAIN>={metrics_raw['train_start']}, "
            f"VAL=[{metrics_raw['val_start']}, {metrics_raw['val_end']}]. "
            f"Pinball Loss avg={metrics_raw['pinball_loss']['avg']:.4f}."
        ),
    )
    logger.info(f"Modelo registrado: {model.resource_name}")
    return model


def main() -> None:
    client = get_bq_client()
    folds_df = get_folds(client)
    fold5 = folds_df.iloc[-1]

    train_start = str(fold5["train_start"])
    val_start = str(fold5["val_start"])
    val_end = str(fold5["val_end"])

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-gcs-dir",
        default=None,
        help=(
            "Si se pasa, salta submit_training_job() y solo lee metrics.json + "
            "registra en Model Registry desde este directorio ya existente -- "
            "para reintentar el registro sin re-entrenar (ej. tras un fix en "
            "register_model() como el de serving_container_image_uri)."
        ),
    )
    args = parser.parse_args()

    if args.model_gcs_dir:
        run_id = args.model_gcs_dir.rstrip("/").split("/")[-2]  # .../{run_id}/model
        model_gcs_dir = args.model_gcs_dir
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        model_gcs_dir = submit_training_job(train_start, val_start, val_end, run_id)

    metrics_raw = read_metrics(model_gcs_dir)
    register_model(model_gcs_dir, metrics_raw, run_id)


if __name__ == "__main__":
    main()
