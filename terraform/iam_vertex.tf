## Fase 7 -- permiso "actAs" que faltaba: para que un CustomJob de Vertex AI
## corra CON la identidad de mle-m5-sa, el llamador necesita
## roles/iam.serviceAccountUser SOBRE esa misma cuenta -- no basta con los
## roles de Fase 1 (bigquery.admin/storage.admin/aiplatform.admin), esos
## dan permisos SOBRE recursos, no permiso para "actuar como" la cuenta.
## Se descubrio al lanzar el primer CustomJob (submit_training_job.py):
## "You do not have permission to act as service_account: mle-m5-sa...".
## Esto aplica incluso siendo la Workstation la que llama con la propia
## identidad de mle-m5-sa (self-impersonation) -- GCP lo exige igual.

resource "google_service_account_iam_member" "m5_sa_can_act_as_self" {
  service_account_id = data.google_service_account.m5_sa.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${data.google_service_account.m5_sa.email}"
}
