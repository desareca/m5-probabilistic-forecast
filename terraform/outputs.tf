output "tfstate_bucket_name" {
  description = "Name of the Terraform state bucket"
  value       = google_storage_bucket.tfstate_bucket.name
}

output "bucket_name" {
  description = "Name of the GCS bucket for data and artifacts"
  value       = google_storage_bucket.m5_bucket.name
}

output "bucket_uri" {
  description = "URI of the GCS bucket"
  value       = "gs://${google_storage_bucket.m5_bucket.name}"
}

output "dataset_id" {
  description = "BigQuery Dataset ID"
  value       = google_bigquery_dataset.m5_dataset.dataset_id
}

output "service_account_email" {
  description = "Service Account email"
  value       = data.google_service_account.m5_sa.email
}

output "project_id" {
  description = "GCP Project ID"
  value       = var.project_id
}
