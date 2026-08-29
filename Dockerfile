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
# src/common.py, src/evaluation/metrics.py y src/models/lgbm_quantile.py
# (que importa de src/common.py, no de src/models/arima_baseline.py --
# ver src/common.py para el porque de esa separacion).
COPY src/ src/
COPY pipelines/training_job.py pipelines/training_job.py

# "python -m pipelines.training_job", no "python pipelines/training_job.py":
# invocar como script suelto solo agrega /app/pipelines a sys.path, no /app
# -- rompe el import de src/ (ModuleNotFoundError: No module named 'src').
# Con -m, /app (el WORKDIR, via cwd) queda en el path y src/ se resuelve bien.
ENTRYPOINT ["python", "-m", "pipelines.training_job"]
