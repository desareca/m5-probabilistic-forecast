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
| 4. Modelos | 🔄 En progreso | 4a (ARIMA clásico) con código listo, ejecución pendiente. 4b (BQML ARIMA_PLUS) y 4c (LightGBM) diseñados en `INSTRUCCIONES.md`, código pendiente |
| 5. Validación (walk-forward CV) | ⏳ Pendiente | Diseño de esquema temporal ya definido (`window_size=365`) |
| 6. Evaluación | ⏳ Pendiente | Estructura de comparación (Tabla A/B) ya definida |
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
│   ├── models/                  # ARIMA, BQML, LightGBM (Fase 4)
│   └── evaluation/               # Pinball Loss + comparativas (Fase 6)
├── sql/                          # Queries de construcción de tablas BigQuery
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

## Decisiones de diseño destacadas

- **Pinball Loss como métrica principal** (no RMSE) — penaliza asimétricamente, coherente con
  que sub-stockear y sobre-stockear tienen costos de negocio distintos.
- **Walk-forward CV, no K-Fold** — obligatorio para series temporales, evita leakage.
- **Test set físicamente bloqueado** — los últimos 28 días viven en un archivo separado
  (`sales_train_evaluation.csv`) que no se carga a BigQuery hasta la evaluación final (Fase 6).
- **Comparación de modelos en dos alcances** (Tabla A: 32 series / los 3 modelos; Tabla B:
  30,490 series / 2 modelos) — evita comparar poblaciones distintas bajo una sola tabla.
- Más decisiones y su razonamiento completo en `INSTRUCCIONES.md`.

## Autor

[@desareca](https://github.com/desareca)
