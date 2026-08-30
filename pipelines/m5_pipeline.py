"""
Pipeline de Vertex AI (KFP v2) -- Fase 7, Tarea 3.

5 componentes segun INSTRUCCIONES.md: ingest -> features -> train ->
evaluate -> register.

Decisiones de diseno (dataset M5 estatico, no hay datos "frescos" que
llegar a buscar cada mes -- a diferencia de un pipeline productivo real):

- ingest_component: no hay nada que "cargar" (Fase 2 ya lo hizo una vez y
  no cambia). Se implementa como un chequeo de salud -- valida que las
  tablas base tengan filas -- para que el pipeline falle rapido y con un
  mensaje claro si algo rio arriba se borro o quedo vacio, en vez de fallar
  3 pasos despues con un error críptico. Sin fallback silencioso.
- features_component: SI reconstruye features_train de verdad (no es un
  no-op), pero de forma idempotente -- si la tabla ya tiene filas, omite
  el rebuild (11.1M filas, join de 3 tablas -- recalcularla en cada corrida
  seria caro e innecesario dado que sales_long/calendar/sell_prices no
  cambian). El SQL se lee de sql/build_features_train.sql AL COMPILAR el
  pipeline (no se duplica como string hardcodeado aca) y queda embebido en
  el YAML compilado -- consistente con skill-vertex-ai.md: "el pipeline
  YAML compilado es un artefacto versionable que describe exactamente como
  se entreno el modelo".
- train_component: reutiliza LA MISMA imagen de Artifact Registry de las
  Tareas 1/2 (pipelines/training_job.py) como dsl.container_component, sin
  relanzar un CustomJob anidado -- cada paso del pipeline YA corre como su
  propio job de Vertex AI con los recursos que se le asignen
  (set_cpu_limit/set_memory_limit, aproximando n1-standard-8).
- evaluate_component: compara el Pinball Loss promedio del run contra
  BASELINE_AVG_PINBALL_LOSS (LightGBM, scope completo, promedio de los 5
  folds de Fase 5 -- ver phase-summaries/05-walk-forward-cv.md: p05=0.058,
  p25=0.240, p50=0.379, p75=0.376, p95=0.169 -> avg=0.2444). "Mejora" =
  avg mas bajo. Baseline hardcodeado a proposito (no hay aun un mecanismo
  de "modelo en produccion actual" mas alla de este numero documentado).
- register_component: SOLO corre si evaluate_component confirma mejora
  (dsl.Condition) -- "registra si mejora baseline", literal de INSTRUCCIONES.md.
  Mismo caveat de la Tarea 2: serving_container_image_uri apunta a la
  imagen de training (no es deployable de verdad, ver
  pipelines/submit_training_job.py).

Uso:
    python -m pipelines.compile_pipeline     # genera pipelines/m5_pipeline.yaml
    python -m pipelines.run_pipeline         # compila (si hace falta) y lanza en Vertex AI
"""

import pathlib

from kfp import dsl

PROJECT = "mle-m5-forecast"
REGION = "us-central1"
DATASET = "m5_dataset"
BUCKET = "mle-m5-forecast-m5-bucket"
IMAGE_URI = f"{REGION}-docker.pkg.dev/{PROJECT}/m5-training/lgbm-quantile:v5"

# Ver docstring del modulo -- promedio de 5-fold CV, LightGBM, scope completo.
BASELINE_AVG_PINBALL_LOSS = 0.2444

_SQL_PATH = pathlib.Path(__file__).resolve().parent.parent / "sql" / "build_features_train.sql"
FEATURES_SQL = _SQL_PATH.read_text()

BQ_PACKAGES = ["google-cloud-bigquery==3.12.0", "db-dtypes==1.1.1", "pyarrow==13.0.0"]

# BASE_IMAGE = nuestra propia imagen de Artifact Registry (Tarea 1/2), NO
# una imagen publica de Docker Hub con packages_to_install. Motivo real:
# mirror.gcr.io/library/python:3.10-slim fue rechazado por Vertex AI como
# "Invalid image URI" (Custom Jobs solo aceptan Artifact Registry/GCR/
# Docker Hub, no espejos arbitrarios), y python:3.10-slim (Docker Hub)
# fallaba con exit code 1 sin NINGUN log de contenedor -- consistente con
# el mismo patron de red saliente poco confiable hacia registries/PyPI
# externos que ya vimos en Cloud Shell (docker push con "connection
# refused", resuelto entonces con Cloud Build). Reutilizar la imagen que
# YA sabemos que Vertex AI puede jalar sin problema, sin pip install en
# runtime (packages_to_install tambien depende de salida a PyPI), evita la
# causa raiz en vez de solo cambiar de registry. requirements-training.txt
# ahora incluye google-cloud-aiplatform para que register() tambien
# funcione con esta misma imagen.
BASE_IMAGE = IMAGE_URI


@dsl.component(base_image=BASE_IMAGE)
def ingest_check(project: str, dataset: str) -> None:
    """Chequeo de salud, no una carga real -- ver docstring del modulo."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    tables = ["sales_long", "calendar", "sell_prices", "lgbm_sample"]
    for table in tables:
        count = list(client.query(f"SELECT COUNT(*) AS n FROM `{project}.{dataset}.{table}`").result())[0]["n"]
        if count == 0:
            raise RuntimeError(f"Tabla {table} existe pero esta vacia -- pipeline detenido, sin fallback silencioso.")
        print(f"{table}: {count} filas OK")


@dsl.component(base_image=BASE_IMAGE)
def build_features(sql_text: str, project: str, dataset: str) -> None:
    """Reconstruye features_train SOLO si esta vacia/no existe -- idempotente,
    ver docstring del modulo (evita recalcular 11.1M filas en cada corrida)."""
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.features_train"
    try:
        table = client.get_table(table_ref)
        if table.num_rows > 0:
            print(f"features_train ya existe con {table.num_rows} filas -- omitiendo rebuild.")
            return
    except NotFound:
        pass

    print("features_train no existe o esta vacia -- ejecutando build_features_train.sql...")
    client.query(sql_text).result()
    print("features_train reconstruida.")


@dsl.container_component
def train(train_start: str, val_start: str, val_end: str, output_gcs_path: str):
    return dsl.ContainerSpec(
        image=IMAGE_URI,
        command=["python", "-m", "pipelines.training_job"],
        args=[
            "--train-start", train_start,
            "--val-start", val_start,
            "--val-end", val_end,
            "--output-gcs-path", output_gcs_path,
        ],
    )


@dsl.component(base_image=BASE_IMAGE)
def evaluate(model_gcs_dir: str, baseline_avg_pinball_loss: float) -> bool:
    """True si el avg Pinball Loss del run mejora (es menor a) el baseline."""
    import json

    from google.cloud import storage

    assert model_gcs_dir.startswith("gs://")
    bucket_name, _, prefix = model_gcs_dir[len("gs://"):].partition("/")
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(f"{prefix.rstrip('/')}/metrics.json")
    metrics = json.loads(blob.download_as_text())

    avg = metrics["pinball_loss"]["avg"]
    improved = avg < baseline_avg_pinball_loss
    print(f"avg Pinball Loss = {avg:.4f} vs baseline = {baseline_avg_pinball_loss:.4f} -> mejora={improved}")
    return improved


@dsl.component(base_image=BASE_IMAGE)
def register(model_gcs_dir: str, project: str, region: str, serving_image: str, run_id: str) -> str:
    """Mismo criterio de labels/serving_container que pipelines/submit_training_job.py
    (Tarea 2) -- ver ese archivo para el caveat de por que serving_image no
    es realmente deployable."""
    import json
    import re

    from google.cloud import aiplatform, storage

    assert model_gcs_dir.startswith("gs://")
    bucket_name, _, prefix = model_gcs_dir[len("gs://"):].partition("/")
    blob = storage.Client().bucket(bucket_name).blob(f"{prefix.rstrip('/')}/metrics.json")
    metrics = json.loads(blob.download_as_text())

    def sanitize(value: str) -> str:
        return re.sub(r"[^a-z0-9_-]", "_", str(value).lower())

    labels = {"run_id": sanitize(run_id), "source": "kfp_pipeline"}
    for q_name, loss in metrics["pinball_loss"].items():
        labels[f"pinball_{q_name}"] = sanitize(f"{loss:.4f}")

    aiplatform.init(project=project, location=region)
    model = aiplatform.Model.upload(
        display_name=f"lgbm-quantile-{run_id}",
        artifact_uri=model_gcs_dir,
        serving_container_image_uri=serving_image,
        labels=labels,
        description=f"Registrado via KFP pipeline. Pinball Loss avg={metrics['pinball_loss']['avg']:.4f}.",
    )
    print(f"Modelo registrado: {model.resource_name}")
    return model.resource_name


@dsl.pipeline(
    name="m5-lgbm-quantile-pipeline",
    description="Fase 7: ingest (chequeo) -> features (idempotente) -> train -> evaluate -> register (condicional).",
)
def m5_pipeline(
    train_start: str,
    val_start: str,
    val_end: str,
    run_id: str,
    baseline_avg_pinball_loss: float = BASELINE_AVG_PINBALL_LOSS,
):
    output_gcs_path = f"gs://{BUCKET}/models/lgbm_quantile/{run_id}"

    ingest_task = ingest_check(project=PROJECT, dataset=DATASET)

    features_task = build_features(sql_text=FEATURES_SQL, project=PROJECT, dataset=DATASET)
    features_task.after(ingest_task)

    train_task = train(
        train_start=train_start, val_start=val_start, val_end=val_end, output_gcs_path=output_gcs_path
    )
    train_task.after(features_task)
    # Aproxima n1-standard-8 (8 vCPU / 30GB) -- ver skill-vertex-ai.md.
    train_task.set_cpu_limit("8")
    train_task.set_memory_limit("30G")

    evaluate_task = evaluate(model_gcs_dir=output_gcs_path, baseline_avg_pinball_loss=baseline_avg_pinball_loss)
    evaluate_task.after(train_task)

    with dsl.Condition(evaluate_task.output == True, name="registrar-si-mejora"):  # noqa: E712
        register(
            model_gcs_dir=output_gcs_path,
            project=PROJECT,
            region=REGION,
            serving_image=IMAGE_URI,
            run_id=run_id,
        )
