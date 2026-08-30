"""
Compila pipelines/m5_pipeline.py a YAML -- Fase 7, Tarea 3.

El YAML compilado es el entregable versionable de INSTRUCCIONES.md
("Pipeline YAML compilado"): describe exactamente los 5 componentes, sus
imagenes/paquetes, y el SQL de features_train embebido tal cual estaba al
compilar (ver docstring de m5_pipeline.py).

--upload-gcs (Fase 7, Tarea 5): ademas de compilar localmente, sube el YAML
a GCS_TEMPLATE_PATH -- el Cloud Scheduler de Tarea 5 dispara la ejecucion
via la REST API de Vertex AI Pipelines apuntando a esa ruta fija
(templateUri), asi que debe existir en GCS ANTES de que el job de Scheduler
se ejecute (o de probarlo a mano con "gcloud scheduler jobs run").

Uso:
    python -m pipelines.compile_pipeline                # solo local
    python -m pipelines.compile_pipeline --upload-gcs    # + publica en GCS
"""

import argparse

from kfp import compiler

from pipelines.m5_pipeline import BUCKET, m5_pipeline

OUTPUT_PATH = "pipelines/m5_pipeline.yaml"
GCS_TEMPLATE_PATH = f"gs://{BUCKET}/pipeline_templates/m5_pipeline.yaml"


def upload_to_gcs(local_path: str, gcs_path: str) -> None:
    from google.cloud import storage

    assert gcs_path.startswith("gs://")
    bucket_name, _, blob_path = gcs_path[len("gs://"):].partition("/")
    storage.Client().bucket(bucket_name).blob(blob_path).upload_from_filename(local_path)
    print(f"Subido a {gcs_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-gcs", action="store_true")
    args = parser.parse_args()

    compiler.Compiler().compile(pipeline_func=m5_pipeline, package_path=OUTPUT_PATH)
    print(f"Pipeline compilado en {OUTPUT_PATH}")

    if args.upload_gcs:
        upload_to_gcs(OUTPUT_PATH, GCS_TEMPLATE_PATH)


if __name__ == "__main__":
    main()
