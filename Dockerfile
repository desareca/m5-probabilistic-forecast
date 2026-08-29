# Fase 7 -- Custom Training Job container para LightGBM Quantile.
# Base minimalista (python:slim), no una imagen pre-armada de Vertex AI:
# no existe container oficial de Vertex AI para LightGBM (si para
# sklearn/TF/PyTorch/XGBoost), asi que un custom container es el patron
# esperado aca -- ver skill-vertex-ai.md.

FROM python:3.10-slim

WORKDIR /app

COPY requirements-training.txt .
RUN pip install --no-cache-dir -r requirements-training.txt

# Solo el codigo que pipelines/training_job.py importa en runtime --
# src/evaluation/metrics.py y src/models/lgbm_quantile.py (que a su vez
# importa src/models/arima_baseline.py por las constantes PROJECT/DATASET/
# QUANTILE_LEVELS/get_bq_client/write_to_bigquery/fetch_date_window).
COPY src/ src/
COPY pipelines/training_job.py pipelines/training_job.py

ENTRYPOINT ["python", "pipelines/training_job.py"]
