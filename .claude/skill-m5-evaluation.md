---
name: m5-evaluation
file: skill-m5-evaluation.md
description: >
  Patrones y decisiones de diseño para evaluación de forecasting probabilístico
  en el dataset M5. Usar cuando el usuario necesite: implementar Pinball Loss,
  diseñar walk-forward validation, comparar modelos baseline vs challenger,
  analizar errores en series difíciles, o decidir el esquema de corte
  temporal. También usar ante cualquier pregunta sobre data leakage en
  features de series temporales o interpretación de métricas probabilísticas.
---

# M5 Evaluation — Forecasting Probabilístico

## Principios de diseño

**Pinball Loss, no RMSE.** El proyecto predice distribuciones, no valores
puntuales. El RMSE mide error en la mediana implícitamente y no captura
la calidad de los extremos (P5, P95) que son los que importan para
decisiones de inventario. Pinball Loss penaliza cada percentil
independientemente y es la métrica oficial de M5 Uncertainty.

**Walk-forward CV es obligatorio.** K-Fold clásico introduce data leakage
en series temporales porque mezcla observaciones futuras en el train.
Walk-forward garantiza que siempre se entrena en el pasado y se valida
en el futuro. No hay excepciones a esta regla en este proyecto.

**Test set bloqueado hasta el final.** Los últimos 28 días del dataset
no se tocan hasta la evaluación final. Ni para EDA, ni para debugging,
ni para calibrar umbrales. Mirar el test set antes invalida la evaluación.

**Rolling window con tamaño a definir en EDA.** El train tiene tamaño
fijo y se desplaza hacia adelante en cada fold. Esto asume que la historia
reciente es más relevante que la historia lejana. El tamaño de la ventana
se decide durante el EDA analizando estabilidad de patrones y autocorrelación.
Candidatos: 365 días (un ciclo estacional completo) o 730 días (más robusto
ante variaciones interanuales). Implementar `window_size` como parámetro
configurable para poder comparar ambas opciones.

## Pinball Loss

La Pinball Loss penaliza asimétricamente según el percentil: subestimar
tiene diferente costo que sobreestimar, y ese costo varía por percentil.
Para P95, subestimar es mucho más penalizado que sobreestimar — esto
refleja el costo real de quedarse sin stock.

La interpretación de negocio es directa: P50 minimiza el error absoluto
esperado, P95 minimiza el riesgo de stockout. Un modelo que minimiza
solo RMSE no garantiza buenos intervalos en los extremos.

## Walk-Forward CV

El parámetro más importante es el horizonte: 28 días, igual que el
horizonte de predicción real de M5. Esto garantiza que el CV mide
exactamente la capacidad que importa.

El mínimo de historia de entrenamiento para el primer fold debe ser
al menos 1 año para capturar estacionalidad anual. Con ~1,885 días
disponibles para train+CV se pueden hacer varios folds de 28 días,
lo que da una estimación robusta de performance.

## Esquema temporal

El corte entre train, validación y test debe ser fijo y consistente
entre los tres modelos para que la comparación sea justa. Usar los
mismos dates para ARIMA, BQML y LightGBM. Documentar estos cortes
explícitamente en el código como constantes con nombre, no como
strings hardcodeados en queries.

## Comparativa de modelos

La narrativa de la comparativa es importante para el portfolio: ARIMA
establece el piso estadístico, BQML escala eso a producción pero mantiene
las mismas limitaciones de distribución normal, LightGBM Cuantil supera
ambos y agrega incertidumbre real. Cada paso debe estar justificado por
los números.

Reportar Pinball Loss por percentil Y por categoría. El modelo puede
ser bueno en P50 global pero malo en P95 para FOODS (alta proporción
de ceros). Esas diferencias son los insights más interesantes para
documentar.

## Análisis de casos difíciles

Los tres tipos de series donde los modelos suelen fallar más son: series
con alta proporción de ceros (demanda intermitente), productos nuevos sin
historia suficiente para lags, y semanas con eventos especiales no vistos
en entrenamiento. Identificar y documentar el comportamiento del modelo
en estos casos es lo que muestra profundidad técnica en el portfolio —
no solo reportar el número agregado.

## Prevención de leakage en features

La regla es simple: ninguna feature puede usar información del día que
se está prediciendo ni de días futuros. En SQL, esto se garantiza con
`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`. En Python con pandas,
siempre aplicar `.shift(1)` antes de rolling. Claude Code debe verificar
esta condición en cada feature nueva que construya y documentarlo
explícitamente en el código.
