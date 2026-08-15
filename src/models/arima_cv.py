"""
ARIMA clasico -- Fase 5, walk-forward CV.

Reutiliza integramente la logica de src/models/arima_baseline.py (fetch de
la muestra, fetch de ventas por ventana, fit_and_forecast por serie) --
esas funciones ya eran genericas en train_start/val_end, no dependian del
fold unico del smoke test de Fase 4 mas que en fetch_date_window(), que
aca se reemplaza por los 5 folds de src/evaluation/folds.py.

A diferencia de bqml_arima_cv.py, esto no tiene costo asociado (compute
local en la Workstation, statsmodels/pmdarima) -- por eso el fold 5 se
vuelve a correr aca en vez de solo reetiquetar las filas de
arima_predictions/arima_metadata (Fase 4a): mas simple y evita un paso de
migracion fragil, a costo de unos pocos segundos extra de CPU.

Uso:
    python -m src.models.arima_cv               # los 5 folds
    python -m src.models.arima_cv --fold 3        # un solo fold
"""

import argparse
import logging

import pandas as pd
from google.cloud import bigquery

from src.evaluation.cv_io import write_fold
from src.evaluation.folds import get_folds
from src.models.arima_baseline import (
    DATASET,
    PROJECT,
    fetch_sample_metadata,
    fetch_sample_series,
    fit_and_forecast,
    get_bq_client,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.arima_predictions_cv"
METADATA_TABLE = f"{PROJECT}.{DATASET}.arima_metadata_cv"

PREDICTIONS_SCHEMA = [
    bigquery.SchemaField("item_id", "STRING"),
    bigquery.SchemaField("store_id", "STRING"),
    bigquery.SchemaField("date", "DATE"),
    bigquery.SchemaField("p05", "FLOAT"),
    bigquery.SchemaField("p25", "FLOAT"),
    bigquery.SchemaField("p50", "FLOAT"),
    bigquery.SchemaField("p75", "FLOAT"),
    bigquery.SchemaField("p95", "FLOAT"),
    bigquery.SchemaField("fold_id", "INTEGER"),
]
METADATA_SCHEMA = [
    bigquery.SchemaField("item_id", "STRING"),
    bigquery.SchemaField("store_id", "STRING"),
    bigquery.SchemaField("fold_id", "INTEGER"),
    bigquery.SchemaField("categoria_zero_rate", "STRING"),
    bigquery.SchemaField("p", "INTEGER"),
    bigquery.SchemaField("d", "INTEGER"),
    bigquery.SchemaField("q", "INTEGER"),
    bigquery.SchemaField("aic", "FLOAT"),
    bigquery.SchemaField("convergio", "BOOLEAN"),
    bigquery.SchemaField("razon_fallo", "STRING"),
]


def run_fold(client: bigquery.Client, sample_df: pd.DataFrame, fold: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    fold_id = int(fold["fold_id"])
    train_start = pd.Timestamp(fold["train_start"])
    val_start = pd.Timestamp(fold["val_start"])
    val_end = pd.Timestamp(fold["val_end"])

    logger.info(f"=== Fold {fold_id}: TRAIN {train_start.date()}->{fold['train_end']}  VAL {val_start.date()}->{val_end.date()} ===")

    series_df = fetch_sample_series(client, train_start, val_end)
    val_dates = pd.date_range(val_start, val_end, freq="D")

    predictions_rows = []
    metadata_rows = []

    for i, row in sample_df.iterrows():
        item_id, store_id, categoria_zero_rate = row["item_id"], row["store_id"], row["categoria_zero_rate"]

        serie = series_df[
            (series_df["item_id"] == item_id) & (series_df["store_id"] == store_id)
        ].sort_values("date")
        train_serie = serie[serie["date"] < val_start]
        train_sales = train_serie["sales"].to_numpy(dtype=float)

        logger.info(
            f"  [fold {fold_id}][{i + 1}/{len(sample_df)}] {item_id}/{store_id} "
            f"(categoria_zero_rate={categoria_zero_rate}, n_train={len(train_sales)})"
        )

        fit_result = fit_and_forecast(train_sales, val_dates)

        metadata_rows.append(
            {
                "item_id": item_id,
                "store_id": store_id,
                "fold_id": fold_id,
                "categoria_zero_rate": categoria_zero_rate,
                "p": fit_result["p"],
                "d": fit_result["d"],
                "q": fit_result["q"],
                "aic": fit_result["aic"],
                "convergio": fit_result["convergio"],
                "razon_fallo": fit_result["razon_fallo"],
            }
        )

        if fit_result["convergio"]:
            q_df = fit_result["quantiles_df"].copy()
            q_df["item_id"] = item_id
            q_df["store_id"] = store_id
            q_df["fold_id"] = fold_id
            predictions_rows.append(q_df)
        else:
            logger.warning(f"    -> FALLO: {fit_result['razon_fallo']}")

    metadata_df = pd.DataFrame(metadata_rows)
    cols = ["item_id", "store_id", "date", "p05", "p25", "p50", "p75", "p95", "fold_id"]
    predictions_df = (
        pd.concat(predictions_rows, ignore_index=True)[cols] if predictions_rows else pd.DataFrame(columns=cols)
    )

    return predictions_df, metadata_df


def print_cv_convergence_summary(all_metadata_df: pd.DataFrame) -> None:
    summary = (
        all_metadata_df.groupby(["fold_id", "categoria_zero_rate"])["convergio"]
        .agg(n_series="count", n_convergio="sum")
        .assign(n_fallo=lambda d: d["n_series"] - d["n_convergio"])
    )
    logger.info("Resumen de convergencia por fold x categoria_zero_rate:\n%s", summary.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIMA clasico walk-forward CV (Fase 5).")
    parser.add_argument("--fold", type=int, default=None, help="Correr un solo fold_id (1-5)")
    args = parser.parse_args()

    client = get_bq_client()
    sample_df = fetch_sample_metadata(client)
    folds_df = get_folds(client)

    folds_to_run = folds_df[folds_df["fold_id"] == args.fold] if args.fold else folds_df
    if folds_to_run.empty:
        raise ValueError(f"fold_id={args.fold} no existe en cv_folds (1-{len(folds_df)})")

    all_metadata = []
    for _, fold in folds_to_run.iterrows():
        predictions_df, metadata_df = run_fold(client, sample_df, fold)
        write_fold(client, predictions_df, PREDICTIONS_TABLE, PREDICTIONS_SCHEMA, int(fold["fold_id"]))
        write_fold(client, metadata_df, METADATA_TABLE, METADATA_SCHEMA, int(fold["fold_id"]))
        all_metadata.append(metadata_df)

    print_cv_convergence_summary(pd.concat(all_metadata, ignore_index=True))
    logger.info("Walk-forward ARIMA completo.")


if __name__ == "__main__":
    main()
