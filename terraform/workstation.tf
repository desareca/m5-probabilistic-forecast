# ─────────────────────────────────────────────────────────────────────────
# Cloud Workstations — Entorno de desarrollo dedicado (VS Code en navegador)
# ─────────────────────────────────────────────────────────────────────────
#
# Decisiones tomadas (2026-07-04):
#   - Machine type: e2-standard-4 (4 vCPU / 16GB). El trabajo pesado corre
#     en BigQuery y Vertex AI, no en la Workstation, así que no se necesita
#     más potencia aquí.
#   - Idle timeout: GCP no permite desactivarlo del todo (mínimo requerido
#     por la API), así que se fija en el máximo permitido (24h) como red de
#     seguridad silenciosa. El apagado real sigue siendo manual, según lo
#     acordado — no depender de este timeout como hábito.
#   - Running timeout: límite duro de 12h por sesión activa, como segunda
#     red de seguridad ante GCP olvidos o sesiones colgadas.
#   - Disco persistente: 100GB, reclaim_policy = DELETE (actualizado
#     2026-07-13). Decisión: dado uso esporádico, el cluster completo se
#     arma y se destruye entre sesiones (ver scripts/start-session.sh y
#     scripts/stop-session.sh) en vez de dejarlo corriendo — el cargo de
#     cluster ($0.20/h) corre 24/7 mientras el cluster exista, sin importar
#     si la workstation está encendida o apagada. Con RETAIN el disco
#     quedaba huérfano al destruir el cluster (no se puede re-adjuntar a
#     un cluster nuevo) y seguía cobrando aparte. Con DELETE, destruir el
#     cluster limpia todo sin dejar recursos sueltos. El costo es perder
#     el estado de /home entre sesiones — aceptable porque el repo vive en
#     GitHub y los artefactos van a GCS, no local.

# APIs necesarias para Cloud Workstations
resource "google_project_service" "workstations_api" {
  project            = var.project_id
  service            = "workstations.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "compute_api" {
  project            = var.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

# Red por defecto del proyecto (ya existe en todo proyecto GCP nuevo)
data "google_compute_network" "default" {
  name = "default"

  depends_on = [google_project_service.compute_api]
}

data "google_compute_subnetwork" "default" {
  name   = "default"
  region = var.region

  depends_on = [google_project_service.compute_api]
}

# Cluster de Workstations
resource "google_workstations_workstation_cluster" "m5_cluster" {
  provider                = google-beta
  workstation_cluster_id = "m5-forecast-cluster"
  location                = var.region
  network                 = data.google_compute_network.default.id
  subnetwork               = data.google_compute_subnetwork.default.id

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }

  depends_on = [google_project_service.workstations_api]
}

# Configuración de la Workstation (define la "plantilla": máquina, disco, imagen)
resource "google_workstations_workstation_config" "m5_config" {
  provider                = google-beta
  workstation_config_id  = "m5-forecast-config"
  workstation_cluster_id = google_workstations_workstation_cluster.m5_cluster.workstation_cluster_id
  location                = var.region

  host {
    gce_instance {
      machine_type                 = "e2-standard-4"
      boot_disk_size_gb            = 100
      disable_public_ip_addresses  = false
      service_account               = data.google_service_account.m5_sa.email
      service_account_scopes        = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }

  persistent_directories {
    mount_path = "/home"
    gce_pd {
      size_gb        = 100
      disk_type      = "pd-balanced"
      fs_type        = "ext4"
      reclaim_policy = "DELETE"
    }
  }

  # Máximo permitido por GCP — ver nota arriba, el apagado real es manual
  idle_timeout    = "86400s" # 24h
  running_timeout = "43200s" # 12h — red de seguridad ante sesiones olvidadas

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }
}

# La Workstation en sí (la instancia que se enciende/apaga)
resource "google_workstations_workstation" "m5_dev" {
  provider                 = google-beta
  workstation_id          = "m5-dev-workstation"
  workstation_config_id   = google_workstations_workstation_config.m5_config.workstation_config_id
  workstation_cluster_id  = google_workstations_workstation_cluster.m5_cluster.workstation_cluster_id
  location                 = var.region

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }
}

# ── Outputs ─────────────────────────────────────────────────────────────
output "workstation_cluster_id" {
  description = "ID del cluster de Cloud Workstations"
  value       = google_workstations_workstation_cluster.m5_cluster.workstation_cluster_id
}

output "workstation_config_id" {
  description = "ID de la configuración de Workstation"
  value       = google_workstations_workstation_config.m5_config.workstation_config_id
}

output "workstation_id" {
  description = "ID de la Workstation (usar con: gcloud workstations start/stop)"
  value       = google_workstations_workstation.m5_dev.workstation_id
}
