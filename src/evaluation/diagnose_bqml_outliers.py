"""
Diagnostico de valores extremos en bqml_predictions_cv.

Hallazgo en build_cv_metrics.py: el promedio de Pinball Loss "scope
completo" (~3,000 series) para BQML salio en el orden de 1e38-1e39 en
p75/p95, mientras p05/p25 se ven normales. Explicacion: GREATEST(valor, 0)
en predict_bqml_arima.sql / bqml_arima_cv.py recorta el lado negativo
(z-score negativo de p05/p25) pero no el positivo -- si standard_error es
astronomico para alguna serie, p75/p95 explotan sin filtro y p05/p25 se
esconden en 0. Es la misma familia de problema que las 22 series con
standard_error=NaN documentadas para el run de referencia de 4b
(bqml_metadata) -- aca se manifiesta como un numero finito pero absurdo
en vez de NaN.

Objetivo de este script: cuantificar cuantas filas/series estan afectadas
y en que folds, para decidir tratamiento (excluir + documentar, igual que
las series NaN de 4b -- NUNCA promediar silenciosamente).

Uso:
    python -m src.evaluation.diagnose_bqml_outliers
"""

import logging

from src.evaluation.folds import get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"
BQML_PRED = f"{PROJECT}.{DATASET}.bqml_predictions_cv"

# Ventas diarias reales en M5 son de un solo o doble digito para la enorme
# mayoria de series -- cualquier prediccion de 3+ digitos ya es sospechosa,
# pero uso 1000 para aislar los casos verdaderamente patologicos primero.
THRESHOLD = 1000


def main() -> None:
    client = get_bq_client()

    count_sql = f"""
        SELECT
          fold_id,
          COUNT(*) AS n_filas_extremas,
          COUNT(DISTINCT CONCAT(item_id, '_', store_id)) AS n_series_extremas,
          MAX(GREATEST(p75, p95)) AS max_valor
        FROM `{BQML_PRED}`
        WHERE p75 > {THRESHOLD} OR p95 > {THRESHOLD}
        GROUP BY fold_id
        ORDER BY fold_id
    """
    count_df = client.query(count_sql).to_dataframe()
    logger.info(f"Filas extremas (p75 o p95 > {THRESHOLD}) por fold:\n%s", count_df.to_string(index=False))

    total_sql = f"SELECT COUNT(*) AS total_filas FROM `{BQML_PRED}`"
    total = client.query(total_sql).to_dataframe()["total_filas"].iloc[0]
    n_extremas = count_df["n_filas_extremas"].sum() if len(count_df) else 0
    logger.info(f"Total filas extremas: {n_extremas} de {total} ({100 * n_extremas / total:.3f}%)")

    series_sql = f"""
        SELECT
          item_id, store_id, fold_id,
          COUNT(*) AS n_dias_extremos,
          MIN(p50) AS min_p50, MAX(p50) AS max_p50,
          MAX(p75) AS max_p75, MAX(p95) AS max_p95
        FROM `{BQML_PRED}`
        WHERE p75 > {THRESHOLD} OR p95 > {THRESHOLD}
        GROUP BY item_id, store_id, fold_id
        ORDER BY max_p95 DESC
        LIMIT 30
    """
    series_df = client.query(series_sql).to_dataframe()
    logger.info("Top 30 series/fold mas extremas:\n%s", series_df.to_string(index=False))


if __name__ == "__main__":
    main()
