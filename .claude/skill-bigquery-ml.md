---
name: bigquery-ml
file: skill-bigquery-ml.md
description: >
  Patrones y decisiones de diseño para trabajar con BigQuery en proyectos
  de ML sobre series temporales. Usar cuando el usuario necesite: cargar
  datos a BigQuery, hacer reshape de series temporales, construir features
  en SQL, entrenar modelos BQML ARIMA_PLUS, diseñar tablas agregadas para
  dashboards, u optimizar queries para reducir costo. También usar ante
  cualquier duda sobre data leakage en features SQL o particionamiento
  de tablas.
---

# BigQuery ML — Patrones para series temporales

## Principios de diseño

**Feature engineering en SQL, no en Python.** Con 59M filas, construir
features en Python local es inviable. BigQuery escala horizontalmente sin
costo adicional. Todo lo que se pueda expresar como window function en SQL
debe hacerse ahí.

**Leakage temporal es el error más común.** Toda window function que calcule
features debe usar `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` — el `1
PRECEDING` excluye el día actual. Nunca usar `CURRENT ROW` en features de
entrenamiento. Claude Code debe verificar esto en cada feature que construya.

**Particionamiento por fecha desde el inicio.** Las tablas grandes (sales_long,
features) deben particionarse por mes. Esto reduce costo de queries en
Looker Studio y acelera los filtros temporales en entrenamiento.

**Columnas mínimas en tablas agregadas.** Las tablas para Looker Studio deben
tener solo las columnas que el dashboard necesita. Menos columnas = menos
bytes procesados por query = costo casi cero.

## Reshape wide → long

El M5 viene en formato wide (una columna por día). Para ML necesitas formato
long (una fila por observación por día). Este reshape es el paso más crítico
de la ingesta — el resultado son ~59M filas. Hacerlo en BigQuery SQL con
UNPIVOT, no en pandas. Las columnas de días siguen el patrón `d_1, d_2, ...,
d_1941`, por lo que la query de UNPIVOT debe generarse dinámicamente en Python.

## BQML ARIMA_PLUS

BQML entrena un modelo ARIMA independiente por cada combinación de
`time_series_id_col` — en este caso `item_id + store_id`. Esto significa
30,490 modelos en paralelo, transparente para el usuario.

Decisiones importantes al configurar el modelo: usar `holiday_region = 'US'`
porque los datos son de Walmart USA, activar `auto_arima = TRUE` para que BQ
seleccione los parámetros p/d/q automáticamente, y especificar
`data_frequency = 'DAILY'`.

BQML ARIMA_PLUS solo da predicción puntual e intervalos de confianza
asumiendo normalidad — no hace forecasting probabilístico real por cuantiles.
Esta limitación es parte de la narrativa del proyecto: motiva el paso a
LightGBM Cuantil.

## Tablas agregadas

Crear las tablas agregadas como paso final del pipeline, después del batch
prediction. Deben agrupar predicciones por día/categoría/tienda — no por
item individual. El resultado pasa de millones de filas a miles, haciendo
las queries de Looker Studio prácticamente gratuitas.

Diseñar las tablas pensando en las visualizaciones del dashboard: qué
dimensiones necesita filtrar el usuario, qué métricas necesita ver. Crear
una tabla por tipo de visualización es mejor que una tabla grande con todo.

## Optimización de costos

BigQuery cobra por bytes procesados en columnas seleccionadas, no por número
de filas. Las acciones que más reducen costo: filtrar siempre por partición
de fecha, evitar `SELECT *` en tablas grandes, y usar tablas agregadas como
capa intermedia para el dashboard. Con el tier gratuito de 1TB/mes, el
proyecto completo no debería generar costo en BigQuery.
