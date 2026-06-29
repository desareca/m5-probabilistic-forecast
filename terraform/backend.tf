terraform {
  backend "gcs" {
    bucket = "mle-m5-forecast-tfstate"
    prefix = "terraform/state"
  }
}
