## Fase 7 -- repositorio Docker para el training container de LightGBM
## (el unico de los 3 modelos que corre en Vertex AI Custom Training;
## BQML entrena 100% en BigQuery SQL, ARIMA es un smoke test local).

# Cloud Build API -- necesaria para "gcloud builds submit" (build + push
# de la imagen sin pasar por Docker local). Se agrego despues de que
# "docker push" fallara sistematicamente desde Cloud Shell con
# "connection refused" hacia los endpoints de Artifact Registry -- Cloud
# Build evita el problema porque construye y sube la imagen dentro de la
# red de GCP, no desde la VM efimera de Cloud Shell.
resource "google_project_service" "cloudbuild_api" {
  project            = var.project_id
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "m5_training" {
  location      = var.region
  repository_id = "m5-training"
  description   = "Imagenes Docker para Custom Training Jobs (LightGBM Quantile)"
  format        = "DOCKER"

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }
}
