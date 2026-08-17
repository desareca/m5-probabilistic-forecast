"""
Analisis de casos dificiles -- Fase 6 (INSTRUCCIONES.md pide explicitamente:
series con >50% ceros, productos nuevos sin historia, semanas con eventos
especiales -- ademas de Pinball Loss por categoria FOODS/HOBBIES/HOUSEHOLD).

"Series con >50% ceros" ya esta resuelto por cv_metrics_by_category
(categoria_zero_rate: lento/muy_lento, Fase 5) -- no se repite aca. Este
script cubre los 3 desgloses que faltaban, todos construidos sobre
cv_pinball_loss (build_cv_metrics.py, Fase 6) sin tocar esa tabla:

  1. cv_metrics_by_product_category -- Pinball Loss x categoria real
     (FOODS/HOBBIES/HOUSEHOLD, via series_segments.category, Fase 4).
  2. series_release_dates + cv_metrics_by_release_age -- "producto nuevo"
     definido como fecha de prediccion dentro de los 90 dias posteriores a
     su release_date. release_date = primera semana (wm_yr_wk) con precio
     registrado en sell_prices, mapeada a fecha via calendar -- es la
     definicion oficial de "release" del dataset M5 (antes de esa semana el
     item no se vendia en esa tienda, no es que las ventas fueran 0).
  3. cv_metrics_by_event -- Pinball Loss en dias con evento de calendario
     (is_event, reutilizando la misma logica de features_train.sql) vs. sin
     evento, con Navidad separada aparte (cierre de tienda, caso extremo
     documentado en el EDA).

Todos excluyen bqml_unstable_series, mismo criterio que build_cv_metrics.py.

Uso:
    python -m src.evaluation.build_case_analysis
"""

import logging

from src.evaluation.folds import get_bq_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

PINBALL_TABLE = f"{PROJECT}.{DATASET}.cv_pinball_loss"
SERIES_SEGMENTS_TABLE = f"{PROJECT}.{DATASET}.series_segments"
SELL_PRICES_TABLE = f"{PROJECT}.{DATASET}.sell_prices"
CALENDAR_TABLE = f"{PROJECT}.{DATASET}.calendar"

RELEASE_DATES_TABLE = f"{PROJECT}.{DATASET}.series_release_dates"
BY_PRODUCT_CATEGORY_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_by_product_category"
BY_RELEASE_AGE_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_by_release_age"
BY_EVENT_TABLE = f"{PROJECT}.{DATASET}.cv_metrics_by_event"

# Umbral "producto nuevo": dentro de los primeros 90 dias desde su release.
# Coincide con el horizonte de 28 dias x ~3 folds tempranos -- suficiente
# para que un producto nuevo aparezca en varias VAL windows tempranas de
# folds 1-2 sin lags de 182 dias (lag_182) ya disponibles.
NEW_PRODUCT_DAYS = 90


def build_release_dates_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{RELEASE_DATES_TABLE}` AS
        WITH release_week AS (
          -- Primera semana con precio registrado = definicion oficial M5 de
          -- "release": antes de esta semana el item no se vendia en esta
          -- tienda (no existe fila en sell_prices, no es un 0 de venta real).
          SELECT item_id, store_id, MIN(wm_yr_wk) AS release_wk
          FROM `{SELL_PRICES_TABLE}`
          GROUP BY item_id, store_id
        )
        SELECT
          rw.item_id,
          rw.store_id,
          MIN(c.date) AS release_date
        FROM release_week rw
        JOIN `{CALENDAR_TABLE}` c ON c.wm_yr_wk = rw.release_wk
        GROUP BY rw.item_id, rw.store_id
    """


def build_by_product_category_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{BY_PRODUCT_CATEGORY_TABLE}` AS
        SELECT
          p.model, p.quantile_name, p.quantile_level, seg.category, p.in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(p.pinball_loss) AS avg_pinball_loss
        FROM `{PINBALL_TABLE}` p
        JOIN `{SERIES_SEGMENTS_TABLE}` seg
          ON p.item_id = seg.item_id AND p.store_id = seg.store_id
        WHERE NOT p.bqml_unstable_series
        GROUP BY p.model, p.quantile_name, p.quantile_level, seg.category, p.in_arima_sample
        ORDER BY p.model, p.quantile_level, seg.category
    """


def build_by_release_age_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{BY_RELEASE_AGE_TABLE}` AS
        WITH enriched AS (
          SELECT
            p.model, p.quantile_name, p.quantile_level, p.in_arima_sample,
            p.pinball_loss,
            DATE_DIFF(p.date, r.release_date, DAY) AS days_since_release,
            CASE
              WHEN r.release_date IS NULL THEN 'sin_release_date'
              WHEN DATE_DIFF(p.date, r.release_date, DAY) < 0 THEN 'antes_de_release'
              WHEN DATE_DIFF(p.date, r.release_date, DAY) < {NEW_PRODUCT_DAYS}
                THEN 'nuevo_lt_90d'
              ELSE 'establecido'
            END AS release_age_bucket
          FROM `{PINBALL_TABLE}` p
          LEFT JOIN `{RELEASE_DATES_TABLE}` r
            ON p.item_id = r.item_id AND p.store_id = r.store_id
          WHERE NOT p.bqml_unstable_series
        )
        SELECT
          model, quantile_name, quantile_level, release_age_bucket, in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM enriched
        GROUP BY model, quantile_name, quantile_level, release_age_bucket, in_arima_sample
        ORDER BY model, quantile_level, release_age_bucket
    """


def build_by_event_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{BY_EVENT_TABLE}` AS
        WITH calendar_flags AS (
          -- Misma logica que calendar_event_distance en build_features_train.sql
          -- (is_event, is_christmas), recalculada aca sobre `calendar` (~1,913
          -- filas) en vez de reusar features_train (55M filas, grain distinto).
          SELECT
            date,
            CASE WHEN event_name_1 IS NOT NULL OR event_name_2 IS NOT NULL
                 THEN 1 ELSE 0 END AS is_event,
            CASE WHEN EXTRACT(MONTH FROM date) = 12 AND EXTRACT(DAY FROM date) = 25
                 THEN 1 ELSE 0 END AS is_christmas
          FROM `{CALENDAR_TABLE}`
        ),
        enriched AS (
          SELECT
            p.model, p.quantile_name, p.quantile_level, p.in_arima_sample,
            p.pinball_loss,
            CASE
              WHEN cf.is_christmas = 1 THEN 'navidad'
              WHEN cf.is_event = 1 THEN 'evento'
              ELSE 'sin_evento'
            END AS event_bucket
          FROM `{PINBALL_TABLE}` p
          JOIN calendar_flags cf ON p.date = cf.date
          WHERE NOT p.bqml_unstable_series
        )
        SELECT
          model, quantile_name, quantile_level, event_bucket, in_arima_sample,
          COUNT(*) AS n_obs,
          AVG(pinball_loss) AS avg_pinball_loss
        FROM enriched
        GROUP BY model, quantile_name, quantile_level, event_bucket, in_arima_sample
        ORDER BY model, quantile_level, event_bucket
    """


def run_ddl(client, sql: str, label: str) -> None:
    job = client.query(sql)
    job.result()
    gb = (job.total_bytes_billed or 0) / 1e9
    cost = gb / 1024 * 6.25  # tarifa normal de queries, no BQML
    logger.info(f"{label}: OK -- {gb:.3f} GB facturados (~${cost:.4f})")


def _weighted_pivot(df, index_col: str, index_order: list[str] | None = None):
    """
    Colapsa filas duplicadas de (index_col, model) -- ocurren porque las
    tablas by_* traen in_arima_sample como columna separada (bqml/lgbm
    aparecen una vez por cada valor True/False) -- con promedio ponderado
    por n_obs, no un pivot ingenuo que rompe con indices duplicados.
    """
    weighted = df.assign(weighted=df["avg_pinball_loss"] * df["n_obs"])
    agg = weighted.groupby([index_col, "model"], as_index=False).agg(
        weighted_sum=("weighted", "sum"), n_obs_sum=("n_obs", "sum")
    )
    agg["avg_pinball_loss"] = agg["weighted_sum"] / agg["n_obs_sum"]
    pivot = agg.pivot(index=index_col, columns="model", values="avg_pinball_loss")
    if index_order is not None:
        pivot = pivot.reindex([b for b in index_order if b in pivot.index])
    return pivot[[m for m in ["arima", "bqml", "lgbm"] if m in pivot.columns]]


def print_by_product_category(client) -> None:
    df = client.query(
        f"SELECT * FROM `{BY_PRODUCT_CATEGORY_TABLE}` WHERE quantile_name = 'p50'"
    ).to_dataframe()
    logger.info("=== Pinball Loss (P50) por categoria real (todo lgbm_sample) ===")
    logger.info("\n%s", _weighted_pivot(df, "category").to_string())



def print_by_release_age(client) -> None:
    df = client.query(
        f"SELECT * FROM `{BY_RELEASE_AGE_TABLE}` WHERE quantile_name = 'p50'"
    ).to_dataframe()
    bucket_order = ["nuevo_lt_90d", "establecido", "antes_de_release", "sin_release_date"]
    logger.info("=== Pinball Loss (P50) por antiguedad de release ===")
    logger.info("\n%s", _weighted_pivot(df, "release_age_bucket", bucket_order).to_string())
    logger.info("n_obs por bucket:\n%s", df.groupby("release_age_bucket")["n_obs"].sum().to_string())


def print_by_event(client) -> None:
    df = client.query(
        f"SELECT * FROM `{BY_EVENT_TABLE}` WHERE quantile_name = 'p50'"
    ).to_dataframe()
    bucket_order = ["navidad", "evento", "sin_evento"]
    logger.info("=== Pinball Loss (P50) por tipo de dia (evento/navidad/normal) ===")
    logger.info("\n%s", _weighted_pivot(df, "event_bucket", bucket_order).to_string())
    logger.info("n_obs por bucket:\n%s", df.groupby("event_bucket")["n_obs"].sum().to_string())


def main() -> None:
    client = get_bq_client()

    run_ddl(client, build_by_product_category_sql(), "cv_metrics_by_product_category")
    print_by_product_category(client)

    run_ddl(client, build_release_dates_sql(), "series_release_dates")
    run_ddl(client, build_by_release_age_sql(), "cv_metrics_by_release_age")
    print_by_release_age(client)

    run_ddl(client, build_by_event_sql(), "cv_metrics_by_event")
    print_by_event(client)

    logger.info("Analisis de casos dificiles completo.")


if __name__ == "__main__":
    main()
