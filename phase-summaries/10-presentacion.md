# Fase 10: Presentación del proyecto — Resumen

**Estado:** ✅ COMPLETADA

---

## Objetivo

Dejar el proyecto presentable para portfolio y entrevistas: README completo,
diagrama de arquitectura, notebook de evaluación limpio, `.gitignore` correcto,
repo público.

## Tareas completadas

1. **Notebook `02_evaluation.ipynb`** — revisado y con la sección de
   conclusiones reescrita para separar hallazgos verificables de los datos
   del notebook de interpretaciones que vienen de la documentación del
   proyecto (ej. el supuesto de normalidad de BQML ARIMA_PLUS, documentado
   en `skill-bigquery-ml.md`, no se comprueba con los datos de este notebook).
2. **Diagrama de arquitectura** — `docs/architecture.svg`. Flujo: Kaggle →
   Cloud Storage → BigQuery (raw + features) → 3 modelos en paralelo (ARIMA,
   BQML ARIMA_PLUS, LightGBM en Vertex AI) → BigQuery (predicciones) →
   tablas agregadas → Looker Studio.
3. **README.md** — ya estaba prácticamente completo desde antes (resultados,
   costos, decisiones de diseño); se agregó el diagrama de arquitectura en
   la sección correspondiente y se actualizó la tabla de estado del proyecto.
4. **`.gitignore`** — ya estaba correctamente configurado, sin cambios.
5. **Repo público** — ya existía en `desareca/m5-probabilistic-forecast`,
   sin cambios.
