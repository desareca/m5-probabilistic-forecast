# M5 Probabilistic Forecasting — Contexto para Claude Code

## Instrucciones del proyecto

Lee `INSTRUCCIONES.md` antes de comenzar cualquier tarea. Contiene:
- Stack tecnológico y estructura del repositorio
- Las 10 fases del proyecto con objetivos, tareas y entregables
- Decisiones de diseño importantes y sus justificaciones
- Costos estimados por componente GCP

No asumas nada sobre el proyecto sin haber leído ese archivo primero.

---

## Entorno de trabajo

- **Cloud Workstations** (VS Code en navegador, Linux nativo)
- Autenticación GCP via Application Default Credentials (ADC) — ya configurada
- Proyecto GCP activo: `mle-m5-forecast`
- Repo clonado desde GitHub: `https://github.com/desareca/m5-probabilistic-forecast`

---

## Flujo de trabajo por sesión

**Al empezar:**
1. Encender la Workstation: [consola](https://console.cloud.google.com/workstations?project=mle-m5-forecast) → "Iniciar" en `m5-dev-workstation` (o `gcloud workstations start m5-dev-workstation --cluster=m5-forecast-cluster --config=m5-forecast-config --region=us-central1` desde Cloud Shell/local)
2. Abrir VS Code desde el mismo botón ("Abrir"/"Launch")
3. Terminal integrada (``Ctrl+` ``), luego:
   ```bash
   sudo apt update && sudo apt install -y python3.12-venv
   cd ~/m5-probabilistic-forecast
   source .venv/bin/activate
   git pull
   ```
   (el `apt install` se repite cada sesión porque no persiste; el venv en `.venv/` sí persiste en el disco de 100GB)

**Al terminar:**
1. Commitear y hacer `git push` de cualquier cambio
2. Apagar la Workstation: consola → "Detener" en `m5-dev-workstation` (o `gcloud workstations stop m5-dev-workstation --cluster=m5-forecast-cluster --config=m5-forecast-config --region=us-central1`)

**Notas del entorno:**
- El disco persistente (100GB) se cobra siempre, esté la Workstation encendida o no (~$4-5 USD/mes) — apagar detiene solo el cómputo
- Terraform de la Workstation vive en `terraform/workstation.tf`; el estado de Terraform es remoto (`gs://mle-m5-forecast-tfstate`), así que da igual desde qué máquina se corra `terraform plan/apply`
- Trabajar solo desde la Workstation para todo lo que se **ejecuta** (terraform, gcloud, scripts, notebooks); el entorno local en Windows es solo un mirror pasivo para edición asistida, no para ejecución

---

## Skills disponibles

Consulta el archivo correspondiente en `.claude/` antes de implementar
cualquier componente. Cada skill contiene principios de diseño, patrones
y advertencias sobre errores comunes — no código literal.

| Tarea | Skill |
|---|---|
| Setup GCP, Terraform, errores IAM, autenticación | `.claude/skill-gcp-setup.md` |
| Carga de datos, reshape M5, features SQL, BQML, tablas agregadas | `.claude/skill-bigquery-ml.md` |
| Training jobs, Docker, Model Registry, pipelines KFP, batch prediction | `.claude/skill-vertex-ai.md` |
| Pinball Loss, walk-forward CV, comparativa de modelos, análisis de errores | `.claude/skill-m5-evaluation.md` |

---

## Reglas generales

- Trabajar por Fases y por Tareas.
    - Al completar cada Tarea preguntar si avanzar a la siguiente.
    - Al terminar cada Fase generar un resumen y guardarlo en `phase-summaries/` en formato `.md`.
- Todo artefacto generado (modelos, datos procesados) va en GCS, no local
- Nunca commitear credenciales, data raw ni archivos de modelo grandes
- El test set (últimos 28 días) está bloqueado hasta la evaluación final
- Toda feature debe respetar el corte temporal — verificar leakage en cada una
- Ante cualquier decisión de diseño no cubierta en `INSTRUCCIONES.md`, preguntar antes de implementar
- **Apagar la Workstation al terminar cada sesión de trabajo**
