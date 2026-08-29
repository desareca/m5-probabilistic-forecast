"""
Compila (si hace falta) y lanza pipelines/m5_pipeline.yaml como PipelineJob
en Vertex AI Pipelines -- Fase 7, Tarea 3.

Misma ventana temporal (fold 5) que submit_training_job.py (Tarea 2) --
consistencia deliberada, ver ese archivo. run_id distinto por corrida evita
pisar el output_gcs_path de corridas anteriores.

Uso:
    python -m pipelines.run_pipeline
"""

import logging
import os
from datetime import datetime, timezone

from google.cloud import aiplatform

from pipelines.compile_pipeline import OUTPUT_PATH
from pipelines.m5_pipeline import BASELINE_AVG_PINBALL_LOSS, BUCKET, PROJECT, REGION, m5_pipeline
from src.evaluation.folds import get_bq_client, get_folds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from kfp import compiler

    if not os.path.exists(OUTPUT_PATH):
        compiler.Compiler().compile(pipeline_func=m5_pipeline, package_path=OUTPUT_PATH)
        logger.info(f"Pipeline compilado en {OUTPUT_PATH}")

    client = get_bq_client()
    folds_df = get_folds(client)
    fold5 = folds_df.iloc[-1]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    aiplatform.init(project=PROJECT, location=REGION)

    job = aiplatform.PipelineJob(
        display_name=f"m5-lgbm-quantile-pipeline-{run_id}",
        template_path=OUTPUT_PATH,
        pipeline_root=f"gs://{BUCKET}/pipeline_root",
        parameter_values={
            "train_start": str(fold5["train_start"]),
            "val_start": str(fold5["val_start"]),
            "val_end": str(fold5["val_end"]),
            "run_id": run_id,
            "baseline_avg_pinball_loss": BASELINE_AVG_PINBALL_LOSS,
        },
    )
    logger.info(f"Lanzando PipelineJob (run_id={run_id})...")
    job.run(service_account=f"mle-m5-sa@{PROJECT}.iam.gserviceaccount.com", sync=True)
    logger.info(f"PipelineJob completo: {job.resource_name}")


if __name__ == "__main__":
    main()
