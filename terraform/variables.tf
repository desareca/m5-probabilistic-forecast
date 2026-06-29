variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "mle-m5-forecast"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "dataset_id" {
  description = "BigQuery Dataset ID"
  type        = string
  default     = "m5_dataset"
}
