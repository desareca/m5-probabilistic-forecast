"""
Consolida Pinball Loss de los 3 modelos x 5 folds -- primer entregable real
de comparacion de Fase 6, construido con los datos de walk-forward CV de
Fase 5 (arima_predictions_cv, predictions_lgbm_cv, bqml_predictions_cv).

Punto de diseno importante: ARIMA (4a) solo corrio sobre las 32 series de
arima_sample; BQML y LightGBM corrieron sobre las ~3,000 de lgbm_sample
(que por construccion incluye esas 32, ver phase-summaries/04-modelos.md).
Comparar los 3 modelos "a secas" mezclaria series distintas para cada uno.
Por eso cv_pinball_loss trae una columna in_arima_sample: True solo para
las 32 series presentes en los 3 modelos -- esa es la unica base valida
para una comparacion ARIMA vs BQML vs LightGBM. La comparacion BQML vs
LightGBM sobre las ~3,000 series completas es igual de valida y se reporta
aparte (no hay ARIMA con quien compararla ahi).

Tablas generadas:
  cv_pinball_loss            -- nivel fila: model x fold x item x store x
                                 date x quantile, con y_true/y_pred/loss
  cv_metrics_by_fold_quantile -- AVG(pinball_loss) x model x fold x quantile
  cv_metrics_by_category      -- AVG(pinball_loss) x model x quantile x
                                  categoria_zero_rate (across folds)
  cv_metrics_overall          -- AVG(pinball_loss) x model x quantile
                                  (headline, across folds y series)

Uso:
    python -m src.evaluation.build_cv_metrics
"""

import logging

from src.evaluation.folds import get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

SALES_TABLE = f"{PROJECT}.{DATASET}.sales_long"
SERIES_SEGMENTS_TABLE = f"{PROJECT}.{DATASET}.series_segments"
ARIMA_SAMPLE_TABLE = f"{PROJECT}.{DATASET}.arima_sample"

ARIMA_PRED = f"{PROJECT}.{DATASET}.arima_predictions_cv"
LGBM_PRED = f"{PROJECT}.{DATASET}.predictions_lgbm_cv"
BQML_PRED = f"{PROJECT}.{DATASET}.bqml_predictions_cv"

PINBALL_TABLE = f"{PROJECT}.{DATASET}.cv_pinball_loss"
BY_FOLD_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_by_fold_quantile"
BY_CATEGORY_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_by_category"
OVERALL_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_overall"


def build_pinball_loss_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{PINBALL_TABLE}`
        PARTITION BY date
        CLUSTER BY model, fold_id
        AS
        WITH long_preds AS (
          SELECT 'arima' AS model, fold_id, item_id, store_id, date, quantile_name, y_pred
          FROM `{ARIMA_PRED}`
          UNPIVOT(y_pred FOR quantile_name IN (p05, p25, p50, p75, p95))

          UNION ALL

          SELECT 'lgbm' AS model, fold_id, item_id, store_id, date, quantile_name, y_pred
          FROM `{LGBM_PRED}`
          UNPIVOT(y_pred FOR quantile_name IN (p05, p25, p50, p75, p95))

          UNION ALL

          SELECT 'bqml' AS model, fold_id, item_id, store_id, date, quantile_name, y_pred
          FROM `{BQML_PRED}`
          UNPIVOT(y_pred FOR quantile_name IN (p05, p25, p50, p75, p95))
        ),
        enriched AS (
          SELECT
            lp.model,
            lp.fold_id,
            lp.item_id,
            lp.store_id,
            lp.date,
            lp.quantile_name,
            CASE lp.quantile_name
              WHEN 'p05' THEN 0.05 WHEN 'p25' THEN 0.25 WHEN 'p50' THEN 0.50
              WHEN 'p75' THEN 0.75 WHEN 'p95' THEN 0.95
            END AS quantile_level,
            lp.y_pred,
            s.sales AS y_true,
            seg.categoria_zero_rate,
            (arima_s.item_id IS NOT NULL) AS in_arima_sample
          FROM long_preds lp
          INNER JOIN `{SALES_TABLE}` s
            ON lp.item_id = s.item_id AND lp.store_id = s.store_id AND lp.date = s.date
          LEFT JOIN `{SERIES_SEGMENTS_TABLE}` seg
            ON lp.item_id = seg.item_id AND lp.store_id = seg.store_id
          LEFT JOIN `{ARIMA_SAMPLE_TABLE}` arima_s
            ON lp.item_id = arima_s.item_id AND lp.store_id = arima_s.store_id
        )
        SELECT
          *,
          GREATEST(
            quantile_level * (y_true - y_pred),
            (quantile_level - 1) * (y_true - y_pred)
          ) AS pinball_loss
        FROM enriched
    """


def build_by_fold_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{BY_FOLD_TABLE}` AS
        SELECT
          model, fold_id, quantile_name, quantile_level, in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM `{PINBALL_TABLE}`
        GROUP BY model, fold_id, quantile_name, quantile_level, in_arima_sample
        ORDER BY model, fold_id, quantile_level
    """


def build_by_category_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{BY_CATEGORY_TABLE}` AS
        SELECT
          model, quantile_name, quantile_level, categoria_zero_rate, in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM `{PINBALL_TABLE}`
        GROUP BY model, quantile_name, quantile_level, categoria_zero_rate, in_arima_sample
        ORDER BY model, quantile_level, categoria_zero_rate
    """


def build_overall_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{OVERALL_TABLE}` AS
        SELECT
          model, quantile_name, quantile_level, in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM `{PINBALL_TABLE}`
        GROUP BY model, quantile_name, quantile_level, in_arima_sample
        ORDER BY model, quantile_level
    """


def run_ddl(client, sql: str, label: str) -> None:
    job = client.query(sql)
    job.result()
    gb = (job.total_bytes_billed or 0) / 1e9
    cost = gb / 1024 * 6.25  # tarifa normal de queries, no BQML
    logger.info(f"{label}: OK -- {gb:.3f} GB facturados (~${cost:.4f})")


def print_comparison(client) -> None:
    df = client.query(
        f"SELECT * FROM `{OVERALL_TABLE}` ORDER BY model, quantile_level"
    ).to_dataframe()

    logger.info("=== Comparacion justa (32 series de arima_sample, presentes en los 3 modelos) ===")
    fair = df[df["in_arima_sample"]]
    pivot_fair = fair.pivot(index="quantile_name", columns="model", values="avg_pinball_loss")
    logger.info("\n%s", pivot_fair.to_string())

    logger.info("=== BQML vs LightGBM, scope completo (~3,000 series de lgbm_sample) ===")
    df["weighted"] = df["avg_pinball_loss"] * df["n_obs"]
    full_scope = df.groupby(["model", "quantile_name"], as_index=False).agg(
        weighted_sum=("weighted", "sum"), n_obs_sum=("n_obs", "sum")
    )
    full_scope["avg_pinball_loss"] = full_scope["weighted_sum"] / full_scope["n_obs_sum"]
    pivot_full = full_scope[full_scope["model"].isin(["bqml", "lgbm"])].pivot(
        index="quantile_name", columns="model", values="avg_pinball_loss"
    )
    logger.info("\n%s", pivot_full.to_string())


def main() -> None:
    client = get_bq_client()

    run_ddl(client, build_pinball_loss_sql(), "cv_pinball_loss")
    run_ddl(client, build_by_fold_sql(), "cv_metrics_by_fold_quantile")
    run_ddl(client, build_by_category_sql(), "cv_metrics_by_category")
    run_ddl(client, build_overall_sql(), "cv_metrics_overall")

    print_comparison(client)

    logger.info("Consolidacion de metricas completa.")


if __name__ == "__main__":
    main()
