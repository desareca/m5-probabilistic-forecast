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

- Ninguno pendiente de Fase 1 — el backend remoto de Terraform se completó el 2026-07-05 (ver Adenda abajo).

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

## Adenda — Migración a Cloud Workstation dedicada (2026-07-04 / 2026-07-05)

**Motivo:** Se decidió abandonar el flujo de trabajo local en WSL2 y usar una Cloud Workstation dedicada en GCP, para aislar el proyecto de otros trabajos personales en la misma cuenta de Google (Cloud Shell demostró compartir el mismo home persistente entre todos los proyectos de la cuenta, lo cual no es apto como entorno de trabajo regular).

**Infraestructura agregada vía Terraform (`terraform/workstation.tf`):**
- Workstation Cluster: `m5-forecast-cluster` (us-central1, red `default`)
- Workstation Config: `m5-forecast-config`
  - Máquina: `e2-standard-4` (4 vCPU / 16GB) — suficiente ya que el cómputo pesado corre en BigQuery/Vertex AI, no en la Workstation
  - Disco persistente: 100GB, `pd-balanced` (pd-standard no soporta <200GB), montado en `/home`, `reclaim_policy = RETAIN`
  - Idle timeout: 24h (máximo permitido por la API; el apagado real sigue siendo manual)
  - Running timeout: 12h (red de seguridad ante sesiones olvidadas)
  - Corre como `mle-m5-sa` (misma service account del proyecto)
- Workstation: `m5-dev-workstation`
- APIs adicionales habilitadas vía Terraform: `workstations.googleapis.com`, `compute.googleapis.com`

**Nota técnica:** los recursos `google_workstations_*` requirieron el provider `google-beta` (no estaban en GA todavía en la versión de provider fijada, `~> 5.0` → v5.45.2). Se agregó el provider `google-beta` en `main.tf`.

**Backend remoto de Terraform — cerrado:**
- Bucket `mle-m5-forecast-tfstate` creado (rompiendo el problema de huevo-o-gallina: se aplicó primero con backend local, luego se migró)
- Estado migrado exitosamente de local → `gs://mle-m5-forecast-tfstate`
- Verificado con `terraform plan` → "No changes. Your infrastructure matches the configuration."
- El `terraform.tfstate` local en Windows quedó obsoleto (pendiente de borrar por higiene, ya no se usa)

**Entorno de trabajo actualizado:** `CLAUDE.md` e `INSTRUCCIONES.md` ahora reflejan Cloud Workstations como entorno principal (reemplaza las referencias anteriores a WSL2).

**`requirements.txt` actualizado para Python 3.12** (la imagen base de Cloud Workstations trae 3.12, más nuevo que el 3.10 asumido originalmente). Varios pines de versión no tenían wheels precompilados para 3.12 y fallaban al compilar desde código fuente (numpy.distutils fue removido en 3.12). Ajustes: `pandas` 2.0.3→2.2.2, `numpy` 1.24.3→1.26.4, `scipy` 1.11.2→1.13.1, `scikit-learn` 1.3.0→1.4.2, `statsmodels` 0.14.0→0.14.2, `lightgbm` 4.0.0→4.3.0, `matplotlib` 3.7.2→3.8.4, `pyyaml` 6.0→6.0.2, `black` 23.7.0→24.4.2, `kfp` 2.3.0→2.7.0 (la 2.3.0 nunca existió como release), `google-cloud-aiplatform` 1.32.0→1.60.0 (relaja la dependencia transitiva `shapely` a permitir 2.x).

**Pendiente de esta adenda:**
- Confirmar que `pip install -r requirements.txt` termina sin errores dentro del venv de la Workstation
- Limpiar `terraform.tfstate` local obsoleto en Windows

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
