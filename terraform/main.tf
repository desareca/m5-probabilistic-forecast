terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# GCS Bucket for raw data and artifacts
resource "google_storage_bucket" "m5_bucket" {
  name          = "${var.project_id}-m5-bucket"
  location      = var.region
  force_destroy = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }
}

# BigQuery Dataset
resource "google_bigquery_dataset" "m5_dataset" {
  dataset_id    = var.dataset_id
  friendly_name = "M5 Probabilistic Forecasting"
  description   = "Dataset for M5 Walmart forecasting project"
  location      = var.region

  labels = {
    environment = "production"
    project     = "m5-forecast"
  }

  access {
    role          = "OWNER"
    user_by_email = data.google_service_account.m5_sa.email
  }
}

# Service Account (import existing one from manual creation)
data "google_service_account" "m5_sa" {
  account_id = "mle-m5-sa"
}

# IAM roles for service account
resource "google_project_iam_member" "m5_sa_bigquery_admin" {
  project = var.project_id
  role    = "roles/bigquery.admin"
  member  = "serviceAccount:${data.google_service_account.m5_sa.email}"
}

resource "google_project_iam_member" "m5_sa_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${data.google_service_account.m5_sa.email}"
}

resource "google_project_iam_member" "m5_sa_aiplatform_admin" {
  project = var.project_id
  role    = "roles/aiplatform.admin"
  member  = "serviceAccount:${data.google_service_account.m5_sa.email}"
}
