"""
Pinball Loss -- formula pura, sin dependencias de BigQuery.

Reutilizada por build_cv_metrics.py (agregacion en BQ, ver ese archivo) y
disponible para uso ad-hoc en notebooks (Fase 6, 02_evaluation.ipynb).
"""

import numpy as np


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, quantile: float) -> np.ndarray:
    """
    Pinball Loss (quantile loss) por observacion -- NO promediada.
    quantile in (0, 1). Ver skill-m5-evaluation.md: penaliza asimetricamente,
    subestimar en P95 cuesta mucho mas que sobreestimar (riesgo de stockout).
    """
    error = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return np.maximum(quantile * error, (quantile - 1) * error)


QUANTILE_LEVELS = {"p05": 0.05, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p95": 0.95}
