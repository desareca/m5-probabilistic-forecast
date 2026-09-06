# Fase 9: Dashboard Looker Studio — Resumen Completado

**Fecha inicio:** 2026-09-06
**Fecha fin:** 2026-09-06
**Estado:** ✅ COMPLETADA

---

## Objetivo

Dashboard público en Looker Studio, conectado a las 3 tablas agregadas de Fase 8,
mostrando demanda real vs. predicción, comparativa de modelos y diagnóstico de error.

**Link público:** https://datastudio.google.com/u/0/reporting/fd99acbf-5e6e-4299-a76a-97591b28d26a

---

## Bug crítico encontrado y corregido antes de poder graficar nada

Al conectar `agg_weekly_comparison` a la primera visualización (línea de tiempo P50 vs.
real), la serie mostraba "islas" sin sentido — semanas sueltas en años distintos (2012,
2013, 2014, 2015, 2016) con huecos de meses entre medio. Causa raíz: la tabla combinaba
los 5 folds de walk-forward CV (Fase 5, dispersos 2011-2016 por diseño) con el test real
(Fase 7), sin distinguir origen ni acotar a una ventana temporal continua.

**Fix de scope temporal:** se identificó que el fold 5 (VAL 2016-03-28 → 2016-04-24) y el
test real (2016-04-25 → 2016-05-22) son estrictamente consecutivos — el test real empieza
el día inmediatamente siguiente al fin del fold 5. Se acotaron `agg_predictions` y
`agg_weekly_comparison` a esta única ventana continua de 56 días (8 semanas), descartando
los folds 1-4 (dispersos, sin continuidad, sin utilidad para una serie de tiempo).

**Segundo bug, más sutil, encontrado al verificar el fix anterior:** incluso dentro de la
ventana continua, seguía apareciendo un salto de escala ~10x justo en el empalme
(2016-04-24 → 2016-04-25). Causa: `predictions_lgbm_cv` corre sobre `lgbm_sample` (~3,001
series) pero `predictions_test` (Fase 7, Tarea 4) corrió sobre las 30,490 series
completas — sumar ambas fuentes sin normalizar el universo de series infla el segundo
tramo ~10x. Fix: `INNER JOIN` de `predictions_test` contra `lgbm_sample` en ambas tablas,
para que los dos tramos de la ventana compartan exactamente el mismo universo de series
(confirmado: 3,001 = 3,001 en ambos tramos tras el fix).

Ninguno de los dos bugs era visible en las tablas de Fase 8 tal como quedaron — solo se
manifestaron al intentar graficarlas como serie de tiempo continua, que es un uso que
Fase 8 no había ejercitado todavía.

## Segundo hallazgo — `test_evaluation_metrics` nunca tuvo desglose por categoría

`agg_metrics` solo podía mostrar el Pinball Loss del test real como una fila agregada
`category='ALL'`, porque `evaluate()` en `pipelines/batch_predict.py` (Fase 7) promedia
sobre todo el merge de una sola vez, sin `groupby` por categoría. Se resolvió sin tocar el
resultado original de Fase 7: nuevo script `src/evaluation/build_test_metrics_by_category.py`
que recalcula el Pinball Loss desde `predictions_test + test_labels + series_segments`,
con la misma fórmula pura de `metrics.py`, agregando por categoría. `agg_metrics.sql` ahora
consume esta tabla nueva en vez de la fila `ALL`.

**Dependencia de orden a respetar al reconstruir:** `build_test_metrics_by_category.py`
debe correr *antes* que `sql/aggregations/build_aggregations.py`, porque `agg_metrics.sql`
ahora depende de su output.

## Tercer hallazgo — el modelo subestima el volumen agregado sistemáticamente

Verificado con dos cálculos independientes (vía `agg_weekly_comparison` y directo desde
las tablas base) que dan el mismo número: P50 subestima el total de venta agregada en la
ventana de evaluación en **~27.5%**, con la subestimación empeorando según la tasa de
ceros de cada categoría:

| Categoría | Subestimación |
|---|---|
| FOODS | -21.3% |
| HOUSEHOLD | -38.2% |
| HOBBIES | -47.9% |

Coherente con una propiedad matemática esperada, no un error de calibración: el objetivo
`quantile` de LightGBM para `alpha=0.5` optimiza la mediana por observación individual, y
la mediana de una distribución con alta proporción de ceros es sistemáticamente menor que
la suma/media total — el mismo efecto que ya se documentó en Fase 6 (HOBBIES con la mayor
tasa de ceros, ahora visible también como el mayor error agregado y el mayor error % en
el heatmap por tienda de la página 2 del dashboard).

---

## Estructura del dashboard

**Página 1 — Resumen: Demanda Real vs. Predicción (LightGBM)**
- Serie de tiempo: `actual_sales` vs. `pred_p50` (línea), banda `pred_p05`/`pred_p95`
  (área superpuesta, técnica manual — Looker Studio no soporta línea+área combinadas en un
  solo gráfico de serie temporal)
- Barras de Pinball Loss por modelo × percentil (ARIMA, BQML, LightGBM, LightGBM test real)
- Filtro de `category`
- Fuente: `agg_weekly_comparison`, `agg_metrics`

**Página 2 — Diagnóstico de Error: Detalle por Tienda y Categoría**
- Serie de tiempo diaria (venta vs. predicción) por tienda/categoría
- Tabla dinámica categoría × tienda con `error_pct = (p50 - actual_sales) / actual_sales`,
  estilo mapa de calor activado
- Fuente: `agg_predictions` (con `actual_sales` agregado — no estaba en el diseño
  original de Fase 8, se agregó en Fase 9 para poder calcular error en la misma tabla)

## Decisiones de diseño

- **Eje de fechas en formato "Semana ISO del año ISO"** en vez de fecha diaria — más
  legible para una serie semanal, cambio a nivel de fuente de datos (aplica a todos los
  gráficos que usan el campo automáticamente).
- **Redondeo a 2 decimales en origen (SQL `ROUND()`)**, no vía formato de Looker Studio —
  se propaga automáticamente a todos los gráficos sin configurar cada uno por separado.
- **Nota aclaratoria de scope (~10% muestra) NO agregada como texto en el dashboard** —
  decisión consciente: queda documentada aquí y en el README en su lugar.
- **Credenciales de fuente de datos: "propietario"**, no "el visor debe tener acceso" —
  necesario para que el link público funcione sin que cada visitante necesite permisos
  de BigQuery en `mle-m5-forecast`.

---

## Archivos nuevos/modificados

```
sql/aggregations/agg_predictions.sql          (modificado: fold5+test filtrado a lgbm_sample, + actual_sales)
sql/aggregations/agg_weekly_comparison.sql    (modificado: mismo fix de scope + p25/p75, redondeo)
sql/aggregations/agg_metrics.sql              (modificado: desglose por categoría en test real)
src/evaluation/build_test_metrics_by_category.py  (nuevo)
README.md                                     (nuevo: sección Dashboard, estado Fase 9)
docs/dashboard_preview.png                    (nuevo: captura para el README)
```

---

## Próxima Fase: FASE 10 — Presentación del proyecto

**Pendiente:** README completo con diagrama de arquitectura, notebook de evaluación
limpio y narrativo, `.gitignore` verificado, repo público confirmado.
