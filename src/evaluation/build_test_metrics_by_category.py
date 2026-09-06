"""
Pinball Loss del test set real, desglosado por categoria de producto
(FOODS/HOBBIES/HOUSEHOLD) -- Fase 9.

test_evaluation_metrics (Fase 7, pipelines/batch_predict.py) solo calcula
el Pinball Loss agregado GLOBALMENTE por percentil (evaluate() en ese
script hace .mean() sobre todo el merge de una sola vez, sin groupby por
categoria) -- por eso agg_metrics.sql (Fase 8) solo podia mostrar una fila
'ALL' para el modelo 'lgbm_test_real', a diferencia de los folds de CV que
si tienen desglose por categoria via cv_metrics_by_product_category
(build_case_analysis.py, Fase 6).

Este script llena ese hueco SIN tocar test_evaluation_metrics ni
pipelines/batch_predict.py (serian cambios retroactivos a un resultado ya
documentado de Fase 7) -- recalcula el Pinball Loss desde las tablas base
ya existentes (predictions_test + test_labels + series_segments), con la
misma formula pura de src/evaluation/metrics.py (GREATEST(q*error,
(q-1)*error), error = y_true - y_pred).

Uso:
    python -m src.evaluation.build_test_metrics_by_category
"""

import logging

from src.evaluation.folds import get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.predictions_test"
LABELS_TABLE = f"{PROJECT}.{DATASET}.test_labels"
SERIES_SEGMENTS_TABLE = f"{PROJECT}.{DATASET}.series_segments"
OUTPUT_TABLE = f"{PROJECT}.{DATASET}.test_evaluation_metrics_by_category"


def build_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{OUTPUT_TABLE}` AS
        WITH merged AS (
          SELECT
            p.item_id, p.store_id, p.date, seg.category,
            t.sales AS y_true,
            p.p05, p.p25, p.p50, p.p75, p.p95
          FROM `{PREDICTIONS_TABLE}` p
          INNER JOIN `{LABELS_TABLE}` t
            ON p.item_id = t.item_id AND p.store_id = t.store_id AND p.date = t.date
          JOIN `{SERIES_SEGMENTS_TABLE}` seg
            ON p.item_id = seg.item_id AND p.store_id = seg.store_id
        ),
        long_preds AS (
          SELECT category, y_true, quantile_name, y_pred
          FROM merged
          UNPIVOT(y_pred FOR quantile_name IN (p05, p25, p50, p75, p95))
        ),
        with_loss AS (
          SELECT
            category,
            quantile_name,
            CASE quantile_name
              WHEN 'p05' THEN 0.05 WHEN 'p25' THEN 0.25 WHEN 'p50' THEN 0.50
              WHEN 'p75' THEN 0.75 WHEN 'p95' THEN 0.95
            END AS quantile_level,
            GREATEST(
              (CASE quantile_name WHEN 'p05' THEN 0.05 WHEN 'p25' THEN 0.25 WHEN 'p50' THEN 0.50 WHEN 'p75' THEN 0.75 WHEN 'p95' THEN 0.95 END) * (y_true - y_pred),
              ((CASE quantile_name WHEN 'p05' THEN 0.05 WHEN 'p25' THEN 0.25 WHEN 'p50' THEN 0.50 WHEN 'p75' THEN 0.75 WHEN 'p95' THEN 0.95 END) - 1) * (y_true - y_pred)
            ) AS pinball_loss
          FROM long_preds
        )
        SELECT
          category,
          quantile_name,
          quantile_level,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM with_loss
        GROUP BY category, quantile_name, quantile_level
        ORDER BY category, quantile_level
    """


def run_ddl(client, sql: str, label: str) -> None:
    job = client.query(sql)
    job.result()
    gb = (job.total_bytes_billed or 0) / 1e9
    cost = gb / 1024 * 6.25  # tarifa normal de queries
    logger.info(f"{label}: OK -- {gb:.3f} GB facturados (~${cost:.4f})")


def print_summary(client) -> None:
    df = client.query(f"SELECT * FROM `{OUTPUT_TABLE}` ORDER BY category, quantile_level").to_dataframe()
    pivot = df.pivot(index="quantile_name", columns="category", values="avg_pinball_loss")
    logger.info("=== Pinball Loss test set real, por categoria ===\n%s", pivot.to_string())


def main() -> None:
    client = get_bq_client()
    run_ddl(client, build_sql(), "test_evaluation_metrics_by_category")
    print_summary(client)
    logger.info("test_evaluation_metrics_by_category listo.")


if __name__ == "__main__":
    main()
