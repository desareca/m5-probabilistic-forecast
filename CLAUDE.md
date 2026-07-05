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
