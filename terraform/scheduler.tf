## Fase 7, Tarea 5 -- Cloud Scheduler para disparar el pipeline mensualmente.
##
## CREADO PAUSADO A PROPOSITO (paused = true). El dataset M5 es un CSV
## estatico de Kaggle: sales_long/calendar/sell_prices/features_train
## nunca cambian (build_features_train.sql corre idempotente, ver
## m5_pipeline.py), por lo que una cadencia de calendario ciega
## entrenaria SIEMPRE sobre los mismos datos -- sin señal real de "datos
## nuevos" que justifique un reentrenamiento. La pequeña variacion de
## Pinball Loss observada entre corridas (~0.278 vs ~0.27-0.28) es
## no-determinismo de LightGBM en la construccion de histogramas
## multi-hilo, no aprendizaje de informacion nueva.
##
## Esta pieza demuestra la CAPACIDAD tecnica pedida en INSTRUCCIONES.md
## (Cloud Scheduler -> Vertex AI Pipelines) sin gastar computo real en
## reentrenamientos sin valor. En un escenario de produccion real con
## datos vivos, el trigger correcto no seria un cron mensual sino:
##   (a) llegada de datos nuevos (ej. Pub/Sub al aterrizar un archivo en
##       GCS), o
##   (b) deteccion de drift/degradacion de metricas en produccion vs.
##       baseline (lo que evaluate_component ya sabe medir).
## Documentado tambien en phase-summaries/07-mlops.md.
##
## Requiere que pipelines/m5_pipeline.yaml este publicado en GCS antes de
## activar o probar este job -- ver pipelines/compile_pipeline.py --upload-gcs.
## Para probarlo sin esperar al primer dia del mes ni despausarlo:
##   gcloud scheduler jobs run m5-pipeline-monthly-retrain --location=us-central1

resource "google_project_service" "cloudscheduler_api" {
  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

data "google_project" "current" {
  project_id = var.project_id
}

# Mismo tipo de permiso "actAs" que fallo en la Tarea 2
# (terraform/iam_vertex.tf) pero para el agente de servicio de Cloud
# Scheduler, no para mle-m5-sa actuando sobre si misma: Scheduler necesita
# roles/iam.serviceAccountTokenCreator sobre mle-m5-sa para poder generar
# el oauth_token que el http_target usa al llamar la API de Vertex AI.
# Sin esto, el job fallaria en tiempo de ejecucion con un 403/permission
# denied -- se agrega proactivamente en vez de esperar a que falle.
resource "google_service_account_iam_member" "cloudscheduler_can_impersonate_m5_sa" {
  service_account_id = data.google_service_account.m5_sa.name
  role                = "roles/iam.serviceAccountTokenCreator"
  member              = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

  depends_on = [google_project_service.cloudscheduler_api]
}

resource "google_cloud_scheduler_job" "m5_pipeline_monthly" {
  name        = "m5-pipeline-monthly-retrain"
  description = "Dispara m5-lgbm-quantile-pipeline via REST API de Vertex AI. PAUSADO por defecto -- ver comentario del archivo."
  region      = var.region
  schedule    = "0 6 1 * *" # 06:00 UTC, dia 1 de cada mes
  time_zone   = "UTC"
  paused      = true

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-aiplatform.googleapis.com/v1/projects/${var.project_id}/locations/${var.region}/pipelineJobs"

    headers = {
      "Content-Type" = "application/json"
    }

    # Ventana temporal fija (fold 5 de walk-forward, ver src/evaluation/folds.py):
    # correcto hardcodearla aca -- sales_long no cambia, por lo que MAX(date)
    # seguira dando exactamente esta ventana cada vez que este job dispare.
    # run_id fijo ("scheduled-run"): las corridas via Scheduler pisan el mismo
    # prefijo GCS entre si -- aceptable dado que el job esta pausado y es
    # unicamente demostrativo, no una historia real de reentrenamientos.
    body = base64encode(jsonencode({
      displayName = "m5-lgbm-quantile-pipeline-scheduled"
      templateUri = "gs://${var.project_id}-m5-bucket/pipeline_templates/m5_pipeline.yaml"
      runtimeConfig = {
        parameterValues = {
          train_start               = "2015-03-29"
          val_start                 = "2016-03-28"
          val_end                   = "2016-04-24"
          run_id                    = "scheduled-run"
          baseline_avg_pinball_loss = 0.2444
        }
      }
    }))

    oauth_token {
      service_account_email = data.google_service_account.m5_sa.email
    }
  }

  depends_on = [google_project_service.cloudscheduler_api]
}

output "scheduler_job_name" {
  description = "Nombre del Cloud Scheduler job (para 'gcloud scheduler jobs run <nombre>' de prueba manual)"
  value       = google_cloud_scheduler_job.m5_pipeline_monthly.name
}
