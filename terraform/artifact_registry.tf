## Fase 7 -- repositorio Docker para el training container de LightGBM
## (el unico de los 3 modelos que corre en Vertex AI Custom Training;
## BQML entrena 100% en BigQuery SQL, ARIMA es un smoke test local).

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
