# Fase 1: Setup GCP — Resumen Completado

**Fecha inicio:** 2026-06-28  
**Fecha fin:** 2026-06-28  
**Estado:** ✅ COMPLETADA

---

## Objetivo

Configurar infraestructura base en GCP para el proyecto de forecasting probabilístico del dataset M5 (Walmart).

---

## Tareas Completadas

### 1. Repositorio Git + GitHub
- ✅ Repositorio Git local inicializado
- ✅ Estructura de carpetas creada según especificación en `INSTRUCCIONES.md`
- ✅ `.gitignore` configurado (excluye data raw, credenciales, modelos grandes)
- ✅ `requirements.txt` con dependencias base
- ✅ Repositorio público en GitHub: https://github.com/desareca/m5-probabilistic-forecast
- ✅ Primer commit: estructura e documentación
- ✅ Segundo commit: Terraform para infraestructura

### 2. Proyecto GCP `mle-m5-forecast`
- ✅ Proyecto creado en consola web
- ✅ Project ID: `mle-m5-forecast`
- ✅ Project Number: `646167436505`

### 3. APIs Habilitadas (4/4)
- ✅ BigQuery API
- ✅ Vertex AI API
- ✅ Cloud Storage API
- ✅ Artifact Registry API

### 4. Autenticación
- ✅ `gcloud` CLI instalado y autenticado
- ✅ `gcloud auth application-default login` ejecutado
- ✅ Configuración activa: `project = mle-m5-forecast`

### 5. Infraestructura con Terraform
- ✅ Proyecto Terraform inicializado en `terraform/`
- ✅ Provider Google v5.45.2 configurado
- ✅ Variables en `variables.tf` (project_id, region, dataset_id)
- ✅ GCS bucket principal: `mle-m5-forecast-m5-bucket`
  - Versioning habilitado
  - Lifecycle rule: mantener 3 versiones
  - Labels: environment=production, project=m5-forecast
- ✅ BigQuery dataset: `m5_dataset`
  - Location: us-central1
  - Acceso otorgado a service account `mle-m5-sa`
- ✅ Service account: `mle-m5-sa` (importado, no creado por Terraform)
- ✅ Roles IAM asignados:
  - BigQuery Admin
  - Storage Admin
  - AI Platform Admin

### 6. Herramientas Instaladas
- ✅ Google Cloud SDK (gcloud)
- ✅ Terraform v1.8.0
- ✅ GitHub CLI (gh) — autenticado como `desareca`

---

## Recursos Creados en GCP

| Recurso | Nombre | Region | Estado |
|---------|--------|--------|--------|
| GCS Bucket (datos) | `mle-m5-forecast-m5-bucket` | us-central1 | ✅ Activo |
| BigQuery Dataset | `m5_dataset` | us-central1 | ✅ Activo |
| Service Account | `mle-m5-sa` | N/A | ✅ Activo |

---

## Commits en GitHub

1. **74e603e** — Initial commit: project structure and documentation
   - `.gitignore`, `requirements.txt`, `CLAUDE.md`, `INSTRUCCIONES.md`

2. **7aaedea** — feat: Setup GCP infrastructure with Terraform
   - `terraform/main.tf`, `terraform/variables.tf`, `terraform/outputs.tf`
   - Terraform plan y apply completados exitosamente

---

## Decisiones de Diseño

### ✅ Respetadas

1. **Región única (us-central1)** — Todos los recursos (GCS, BigQuery, Vertex AI) en la misma región para minimizar egress costs

2. **Infrastructure as Code** — Terraform desde el inicio, no consola web manual

3. **Application Default Credentials (ADC)** — Autenticación via `gcloud auth application-default login`, no hardcoded keys

4. **Service account compartida** — Una sola SA con roles apropiados para todo el pipeline

### ⏳ Pendiente (próximas fases)

- **Backend remoto de Terraform en GCS** — Pendiente migrar estado de Terraform del local al bucket `mle-m5-forecast-tfstate` (requiere bucket creado primero sin backend, luego migración)

---

## Verificaciones Completadas

```bash
# Proyecto GCP
gcloud projects describe mle-m5-forecast  # ✓ ACTIVE

# APIs habilitadas
gcloud services list --enabled  # ✓ Todas 4 presentes

# Service account
gcloud iam service-accounts list  # ✓ mle-m5-sa existe y está ENABLED

# Terraform state
ls -la terraform/terraform.tfstate  # ✓ Creado localmente

# GitHub
gh auth status  # ✓ Autenticado como desareca
git remote -v  # ✓ origin → https://github.com/desareca/m5-probabilistic-forecast.git
```

---

## Próxima Fase: FASE 2 — Datos

**Objetivo:** Cargar dataset M5 a BigQuery, reshape wide→long, EDA.

**Tareas:**
1. Instalar Kaggle API y descargar M5 Uncertainty dataset
2. Subir CSVs a GCS
3. Cargar a BigQuery (formato original wide)
4. Reshape wide → long en BigQuery SQL (~59M filas)
5. EDA: distribuciones, ceros, precios, eventos

**Entregable:** Tabla `m5_dataset.sales_long` + notebook `01_eda.ipynb`

---

## Notas

- El proyecto cuesta aproximadamente $5–10 USD en total, pero con crédito inicial de $300 de GCP (cuenta nueva), es efectivamente gratis.
- El test set (últimos 28 días) está bloqueado hasta la evaluación final — no tocar.
- Todas las credenciales están en `.env_local` (no commiteado).
- Terraform state está localmente por ahora; migrar a GCS es recomendado pero no bloqueante.
