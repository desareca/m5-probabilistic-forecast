# M5 Probabilistic Forecasting

Pipeline end-to-end de **forecasting probabilístico** sobre el dataset M5 (Walmart, Kaggle),
construido en GCP como proyecto de portfolio de Machine Learning Engineering. Predice
distribuciones de venta futura (percentiles P5/P25/P50/P75/P95) para 30,490 series
item×tienda, comparando tres niveles de sofisticación de modelo: ARIMA clásico, BigQuery ML
ARIMA_PLUS, y LightGBM Cuantil.

## Por qué probabilístico, no puntual

Las decisiones de inventario necesitan un rango de escenarios, no un único número esperado.
Sub-stockear y sobre-stockear tienen costos distintos y asimétricos — un forecast puntual no
puede representar eso, un forecast de cuantiles sí.

## Dataset

[M5 Forecasting — Uncertainty](https://www.kaggle.com/competitions/m5-forecasting-uncertainty)
(Kaggle): ventas diarias de 3,049 productos × 10 tiendas Walmart (CA/TX/WI), 2011-01-29 a
2016-06-19. 30,490 series, 78.4% con ≥50% de días en cero (demanda intermitente) — el desafío
central del proyecto.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Almacenamiento raw | Google Cloud Storage (GCS) |
| Data warehouse | BigQuery |
| Feature engineering | BigQuery SQL + Python |
| Baseline estadístico | statsmodels ARIMA (`pmdarima.auto_arima`) |
| Baseline cloud | BigQuery ML ARIMA_PLUS |
| Modelo challenger | LightGBM Cuantil |
| Entrenamiento | Vertex AI Custom Training |
| MLOps | Vertex AI Pipelines + Model Registry |
| Predicciones | Vertex AI Batch Prediction |
| Dashboard | Looker Studio |
| Infraestructura | Terraform |
| Entorno de desarrollo | Cloud Workstations (efímera — ver abajo) |

## Arquitectura

Diagrama de arquitectura pendiente (Fase 10). Documentación completa fase por fase, con
decisiones de diseño y su justificación, en [`INSTRUCCIONES.md`](INSTRUCCIONES.md).

## Estado del proyecto

| Fase | Estado | Resumen |
|---|---|---|
| 1. Setup GCP | ✅ Completa | [`phase-summaries/01-setup-gcp.md`](phase-summaries/01-setup-gcp.md) |
| 1b. Workstation efímera | ✅ Completa | [`phase-summaries/01b-workstation-efimera.md`](phase-summaries/01b-workstation-efimera.md) |
| 2. Datos + EDA | ✅ Completa | [`phase-summaries/02-datos-eda.md`](phase-summaries/02-datos-eda.md) |
| 3. Feature Engineering | ✅ Completa | [`phase-summaries/03-feature-engineering.md`](phase-summaries/03-feature-engineering.md) |
| 4. Modelos | ✅ Completa | [`phase-summaries/04-modelos.md`](phase-summaries/04-modelos.md) — ARIMA clásico, BQML ARIMA_PLUS, LightGBM Cuantil |
| 5. Validación (walk-forward CV) | ✅ Completa | [`phase-summaries/05-walk-forward-cv.md`](phase-summaries/05-walk-forward-cv.md) — 5 folds × 3 modelos |
| 6. Evaluación | 🔄 En progreso | Comparación cuantitativa por percentil ya lista (ver Resultados abajo); falta desglose narrativo por categoría y casos difíciles, notebook `02_evaluation.ipynb` |
| 7. MLOps | ⏳ Pendiente | |
| 8. Tablas agregadas | ⏳ Pendiente | |
| 9. Dashboard Looker Studio | ⏳ Pendiente | |
| 10. Presentación | ⏳ Pendiente | |

## Hallazgos clave (EDA + Feature Engineering)

- **78.4%** de las series tienen ≥50% de días en cero — demanda intermitente, el desafío
  central del proyecto. Determina la elección de LightGBM Cuantil como modelo principal.
- **Tendencia anual fuerte:** +57% de venta promedio entre 2011 y 2016.
- **Autocorrelación (ACF):** la serie agregada (detrended) mantiene una meseta 0.42–0.44
  entre lag=365 y lag=546, pero colapsa a ~0 en lag=730 — evidencia directa para fijar
  `window_size=365` en el walk-forward CV en vez de una ventana más larga.
- **Walmart cierra cada 25 de diciembre** — tratado como caso especial determinístico
  (`is_christmas`, tipo de evento propio `Store_Closure`), no como un evento genérico más.
- Coeficiente de variación de precios real: **62–91%** según categoría, más alto de lo
  asumido inicialmente.

## Resultados — comparación de modelos (walk-forward CV, 5 folds)

Pinball Loss promedio por percentil, sobre 5 folds espaciados (`window_size=365`, horizonte
28 días). Detalle completo en
[`phase-summaries/05-walk-forward-cv.md`](phase-summaries/05-walk-forward-cv.md).

**Comparación directa — 32 series presentes en los 3 modelos:**

| Percentil | ARIMA | BQML ARIMA_PLUS | LightGBM Cuantil |
|---|---|---|---|
| P05 | 0.221 | 0.227 | **0.182** |
| P25 | 0.940 | 0.797 | **0.621** |
| P50 | 1.319 | 1.150 | **0.874** |
| P75 | 1.180 | 1.065 | **0.801** |
| P95 | 0.456 | 0.496 | **0.361** |

**BQML vs. LightGBM — escala completa (~3,000 series de `lgbm_sample`):**

| Percentil | BQML ARIMA_PLUS | LightGBM Cuantil |
|---|---|---|
| P05 | 0.093 | **0.058** |
| P50 | 0.459 | **0.379** |
| P95 | 0.274 | **0.169** |

**LightGBM Cuantil gana en los 5 percentiles, en ambos alcances.** Un detalle relevante para
la narrativa técnica: BQML supera a ARIMA clásico en el cuerpo de la distribución (P25–P75)
pero pierde en las colas (P05/P95) — coherente con que `ARIMA_PLUS` deriva sus intervalos
asumiendo normalidad, mientras que LightGBM Cuantil optimiza cada percentil de forma
independiente y maneja mejor los extremos.

Dos bugs de diseño reales, encontrados y corregidos durante la validación (documentados en
detalle en el resumen de Fase 5): un `JOIN` en BigQuery que no podaba por partición y hacía
que el costo estimado de BQML fuera ~300x el real ($104 estimado vs. $0.34 real por fold), y
7 series de BQML con `standard_error` explosivo que distorsionaban el promedio agregado hasta
que se marcaron y excluyeron explícitamente (mismo principio de "sin fallback silencioso" que
las 22 series `NaN` de Fase 4b).

## Cómo trabajar en el proyecto

### 1. Levantar una sesión de trabajo

El entorno de desarrollo es una **Cloud Workstation efímera** — se destruye al final de cada
sesión para no pagar el control plane corriendo 24/7. Ver
[`phase-summaries/01b-workstation-efimera.md`](phase-summaries/01b-workstation-efimera.md)
para el detalle completo de esta decisión.

Desde **Cloud Shell**:

```bash
./scripts/start-session.sh   # ~15-20 min: recrea el cluster + arranca la workstation
```

Al terminar de trabajar:

```bash
./scripts/stop-session.sh    # destruye el cluster para no seguir pagando
```

### 2. Dentro de la workstation (disco nuevo cada sesión)

```bash
git clone https://github.com/desareca/m5-probabilistic-forecast.git
cd m5-probabilistic-forecast
sudo apt update && sudo apt install -y python3.12-venv
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# recrear .env_local con el token de Kaggle (no vive en git)
```

## Estructura del repositorio

```
m5-probabilistic-forecast/
├── notebooks/
│   ├── 01_eda.ipynb            # EDA completo (Fase 2)
│   └── 02_evaluation.ipynb     # Comparativa de modelos (Fase 6, pendiente)
├── src/
│   ├── data/                   # Carga GCS → BigQuery
│   ├── features/                # Fourier + features SQL (Fase 3)
│   ├── models/                  # Fase 4 (smoke test) + Fase 5 (walk-forward CV)
│   │   ├── arima_baseline.py     #   ARIMA clásico, 1 fold (4a)
│   │   ├── arima_cv.py           #   ARIMA clásico, 5 folds (5)
│   │   ├── bqml_arima_cv.py      #   BQML ARIMA_PLUS, 5 folds, acotado a lgbm_sample (5)
│   │   └── lgbm_quantile.py      #   LightGBM Cuantil, 1 fold (4c)
│   │   └── lgbm_cv.py            #   LightGBM Cuantil, 5 folds (5)
│   └── evaluation/               # Walk-forward CV + Pinball Loss (Fase 5-6)
│       ├── folds.py                #   Genera los 5 folds dinámicamente
│       ├── cv_io.py                #   Escritura idempotente por fold_id
│       ├── metrics.py              #   Fórmula de Pinball Loss
│       ├── build_cv_metrics.py     #   Consolida métricas en BigQuery
│       └── diagnose_bqml_outliers.py # Diagnóstico de series inestables
├── sql/                          # Queries de referencia (reshape, muestras, 4b full-scale)
├── pipelines/                     # Vertex AI Pipelines / KFP (Fase 7)
├── terraform/                     # Infraestructura como código
├── scripts/
│   ├── start-session.sh          # Levanta la Cloud Workstation efímera
│   └── stop-session.sh           # La destruye al terminar
├── phase-summaries/               # Resumen de cada fase completada
├── INSTRUCCIONES.md               # Diseño técnico completo, fase por fase
└── CLAUDE.md                      # Índice de contexto para Claude Code
```

## Costos

Proyecto estimado en **~$21–30 USD** total (cubierto por el crédito inicial de $300 de una
cuenta GCP nueva → costo efectivo $0). Desglose completo, incluida la mecánica de precio de
BQML ARIMA_PLUS (que no cobra a la tarifa estándar de BigQuery), en
[`INSTRUCCIONES.md`](INSTRUCCIONES.md#costos-estimados).

**Costos reales incurridos hasta ahora:**

| Componente | Costo real |
|---|---|
| BQML ARIMA_PLUS, referencia full-scale (Fase 4b, 30,490 series) | $18.27 |
| BQML ARIMA_PLUS, walk-forward CV (Fase 5, 5 folds × ~3,000 series) | $1.70 (5 × $0.34) |
| Materialización de tabla pre-filtrada para CV (una vez) | ~$0.37 |
| ARIMA clásico + LightGBM Cuantil (Fases 4/5) | $0 (compute local en la Workstation) |

El hallazgo del bug de `JOIN` sin pruning (ver Resultados arriba) es la diferencia entre este
número real y lo que hubiera costado sin corregirlo: ~$104/fold × 5 folds ≈ $520 solo en
walk-forward CV.

## Decisiones de diseño destacadas

- **Pinball Loss como métrica principal** (no RMSE) — penaliza asimétricamente, coherente con
  que sub-stockear y sobre-stockear tienen costos de negocio distintos.
- **Walk-forward CV, no K-Fold** — obligatorio para series temporales, evita leakage.
- **Test set físicamente bloqueado** — los últimos 28 días viven en un archivo separado
  (`sales_train_evaluation.csv`) que no se carga a BigQuery hasta la evaluación final (Fase 6).
- **Comparación de modelos en dos alcances** (32 series / los 3 modelos; ~3,000 series de
  `lgbm_sample` / BQML vs. LightGBM) — evita comparar poblaciones distintas bajo una sola
  tabla. BQML corre sobre la muestra desde Fase 5 en adelante, no sobre las 30,490 completas
  (que sí se usaron en el run de referencia de Fase 4b) — decisión de costo/tiempo documentada
  en `INSTRUCCIONES.md`.
- Más decisiones y su razonamiento completo en `INSTRUCCIONES.md`.

## Autor

[@desareca](https://github.com/desareca)
