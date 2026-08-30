# Fase 8: Tablas Agregadas — Resumen Completado

**Fecha inicio:** 2026-08-30
**Fecha fin:** 2026-08-30
**Estado:** ✅ COMPLETADA

---

## Objetivo

3 tablas livianas en BigQuery, optimizadas para Looker Studio (Fase 9), sin tocar las
tablas de detalle (millones de filas) desde el dashboard.

---

## Tablas construidas

| Tabla | Filas | GB facturados | Contenido |
|---|---|---|---|
| `agg_predictions` | 5,040 | 0.089 | Predicciones LightGBM (5 folds CV + test real) por día/categoría/tienda |
| `agg_metrics` | 50 | 0.021 | Pinball Loss por modelo × categoría × percentil (alcance justo, 32 series) + test real |
| `agg_weekly_comparison` | 84 | 2.243 | Real vs. predicho semanal por categoría (suma de volumen) |

Costo total: ~$0.014 — despreciable, tier gratuito de BigQuery cubre esto sin problema.

## Decisiones de diseño

- **`agg_predictions`/`agg_weekly_comparison` solo usan LightGBM** (5 folds de walk-forward
  CV + test real, unidos vía `UNION ALL`) — son "la" serie de predicción para el dashboard,
  no una comparativa de modelos. Esa comparativa vive exclusivamente en `agg_metrics`.
- **`agg_metrics` usa el alcance justo (32 series, `in_arima_sample = TRUE`)** de
  `cv_metrics_by_product_category` — el único donde ARIMA/BQML/LightGBM son comparables
  entre sí (ver lección de Fase 6: mezclar alcances distintos produce comparaciones
  espurias).
- **Fila extra `model = 'lgbm_test_real'`** en `agg_metrics`: pone el Pinball Loss real
  del test set (Fase 7) al lado del baseline de CV — soporta directamente el hallazgo de
  Fase 7 (test real ~20% peor que CV) como gráfico comparativo en el dashboard, sin tener
  que explicarlo solo en texto.
- **`agg_weekly_comparison` usa `SUM`, no `AVG`** — la pregunta de negocio real es "cuánta
  demanda total hay esa semana", no el promedio por serie.

## Bug encontrado y corregido

`CREATE TABLE ... PARTITION BY week AS SELECT ... GROUP BY ... ORDER BY` — BigQuery no
permite `ORDER BY` en el `SELECT` final de una tabla particionada
(`Result of ORDER BY queries cannot be partitioned by field 'week'`). Se quitó; no
aportaba nada real de todas formas (el orden de storage no se conserva en una tabla
particionada).

---

## Archivos nuevos

```
sql/aggregations/agg_predictions.sql
sql/aggregations/agg_metrics.sql
sql/aggregations/agg_weekly_comparison.sql
sql/aggregations/build_aggregations.py
```

---

## Próxima Fase: FASE 9 — Dashboard Looker Studio

**Estado:** No iniciada. Trabajo 100% de interfaz web (Looker Studio → BigQuery →
las 3 tablas de esta fase) — sin cómputo, sin Workstation ni Cloud Shell necesarios
salvo para confirmar algún número puntual.
