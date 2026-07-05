---
name: gcp-setup
file: skill-gcp-setup.md
description: >
  Principios y decisiones de diseño para configurar proyectos GCP orientados
  a ML/MLE. Usar cuando el usuario necesite: crear proyecto GCP, configurar
  autenticación, escribir Terraform para infraestructura base, estructurar
  un repositorio ML, o resolver errores de permisos IAM y APIs no habilitadas.
---

# GCP Setup — Patrones para proyectos ML

## Principios de diseño

**Un proyecto GCP por proyecto de portfolio.** Mantener aislamiento limpio
entre proyectos facilita el control de costos, permisos y presentación.
Nunca mezclar con proyectos de trabajo.

**Infraestructura como código desde el inicio.** Usar Terraform aunque el
proyecto sea pequeño — demuestra buenas prácticas y permite reproducibilidad.
El estado de Terraform va en GCS, no local.

**Credenciales siempre via Application Default Credentials (ADC).** Nunca
hardcodear keys en código. En Cloud Workstations, las credenciales ADC
están preconfiguradas automáticamente — no se requiere `gcloud auth`
manual en cada sesión. En Vertex AI, las credenciales se inyectan
automáticamente via la service account del job.

**Región única para todos los recursos.** Mantener GCS, BigQuery y Vertex AI
en la misma región evita costos de egress entre servicios. Para este proyecto:
`us-central1` por disponibilidad de GPUs y menor costo.

**Apagar la Workstation al terminar cada sesión.** Cloud Workstations cobra
por hora de uso. El hábito de apagarla al terminar es la acción más
importante para controlar costos con los créditos de GCP.

## Cloud Workstations

El entorno de desarrollo corre directamente en GCP — sin WSL2, sin
configuración local, sin problemas de PATH entre sistemas operativos.
`gcloud`, `terraform`, Python y las librerías de GCP están disponibles
en la Workstation sin instalación adicional.

El flujo de trabajo estándar: encender Workstation desde la consola GCP →
abrir VS Code en el navegador → clonar repo desde GitHub → trabajar →
commitear → apagar Workstation.

Si se necesita instalar dependencias adicionales, hacerlo con `pip install`
dentro del entorno virtual del proyecto. No instalar paquetes globalmente
en la Workstation.

## APIs a habilitar

Habilitar todas al inicio del proyecto, no bajo demanda. Las APIs relevantes
para este proyecto son BigQuery, Vertex AI, Cloud Storage, Artifact Registry,
Cloud Build y Cloud Scheduler. Verificar siempre que estén activas antes de
depurar errores de permisos.

## Terraform

Usar Terraform para crear el bucket GCS y el dataset BigQuery. Mantener
variables separadas del código (`variables.tf`) para poder cambiar nombres
sin tocar la lógica. El bucket debe tener lifecycle rules para borrar objetos
temporales después de 90 días y controlar costos.

No versionar el estado de Terraform localmente — guardarlo en un bucket GCS
dedicado desde el inicio.

## Estructura del repositorio

La separación entre `src/` (código reutilizable), `pipelines/` (orquestación),
`sql/` (queries BigQuery), `notebooks/` (exploración) y `terraform/`
(infraestructura) es intencional. Evita mezclar lógica de negocio con
infraestructura. Claude Code debe respetar esta estructura al crear archivos.

El `.gitignore` es crítico: excluir data raw, credenciales JSON, archivos
de modelo grandes y estado de Terraform. Nunca commitear archivos `*.json`
de service accounts.

## Errores comunes

Los errores más frecuentes en setup GCP son de tres tipos: API no habilitada
(el mensaje siempre indica cuál), proyecto no configurado en el cliente Python
(pasar `project=` explícito resuelve), y permisos IAM insuficientes (revisar
roles en consola antes de depurar código).

Si aparece un error inesperado de autenticación, verificar que el proyecto
activo sea el correcto con `gcloud config get-value project`. En Cloud
Workstations esto raramente falla — si ocurre, reiniciar la sesión de
la Workstation suele resolverlo.
