"""
LightGBM Quantile -- Fase 5, walk-forward CV.

Reutiliza integramente la logica de src/models/lgbm_quantile.py
(_fetch_features_window, cast_categoricals, train_models, predict_quantiles)
-- ya eran genericas en la ventana de fechas, no dependian del fold unico
del smoke test de Fase 4 mas que en fetch_date_window(), reemplazado aca
por los 5 folds de src/evaluation/folds.py.

Igual que arima_cv.py: sin costo asociado (compute local en la Workstation),
asi que el fold 5 se vuelve a entrenar aca en vez de reetiquetar
predictions_lgbm de Fase 4c -- mas simple, a costo de ~16 min extra de
CPU. Los 5 folds completos rondan ~80 min de entrenamiento total (5 x ~16
min del smoke test), no trivial pero muy por debajo de lo que costaria
inconsistencia de datos entre folds "reusado" y "recalculado".

Cada fold guarda sus 5 modelos (uno por percentil) en un subdirectorio
separado (models/lgbm_quantile/fold_{N}/) -- ver el parametro model_dir
agregado a train_models() en lgbm_quantile.py.

Uso:
    python -m src.models.lgbm_cv               # los 5 folds
    python -m src.models.lgbm_cv --fold 3        # un solo fold
"""

import argparse
import gc
import logging
import os

import pandas as pd
from google.cloud import bigquery

from src.evaluation.cv_io import write_fold
from src.evaluation.folds import get_folds
from src.models.lgbm_quantile import (
    DATASET,
    MODEL_DIR,
    PROJECT,
    cast_categoricals,
    get_bq_client,
    get_reduced_memory_dtypes,
    predict_quantiles,
    train_models,
    _fetch_features_window,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.predictions_lgbm_cv"

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


def run_fold(client: bigquery.Client, fold: pd.Series, dtypes: dict[str, str]) -> pd.DataFrame:
    fold_id = int(fold["fold_id"])
    train_start = pd.Timestamp(fold["train_start"])
    val_start = pd.Timestamp(fold["val_start"])
    val_end = pd.Timestamp(fold["val_end"])
    model_dir = os.path.join(MODEL_DIR, f"fold_{fold_id}")

    logger.info(f"=== Fold {fold_id}: TRAIN {train_start.date()}->{fold['train_end']}  VAL {val_start.date()}->{val_end.date()} ===")

    # Mismo patron de memoria que 4c: TRAIN y VAL nunca coexisten en
    # memoria, exclude_id_cols=True en TRAIN (no se usan como features).
    train_df = _fetch_features_window(
        client, train_start, val_start, dtypes, label=f"fold{fold_id} train", exclude_id_cols=True
    )
    train_df = cast_categoricals(train_df)
    boosters = train_models(train_df, model_dir=model_dir)

    del train_df
    gc.collect()

    val_df = _fetch_features_window(
        client, val_start, val_end + pd.Timedelta(days=1), dtypes, label=f"fold{fold_id} val", exclude_id_cols=False
    )
    val_df = cast_categoricals(val_df)
    predictions_df = predict_quantiles(boosters, val_df)
    predictions_df["fold_id"] = fold_id

    del val_df
    gc.collect()

    return predictions_df


def main() -> None:
    parser = argparse.ArgumentParser(description="LightGBM Quantile walk-forward CV (Fase 5).")
    parser.add_argument("--fold", type=int, default=None, help="Correr un solo fold_id (1-5)")
    args = parser.parse_args()

    client = get_bq_client()
    dtypes = get_reduced_memory_dtypes(client)
    folds_df = get_folds(client)

    folds_to_run = folds_df[folds_df["fold_id"] == args.fold] if args.fold else folds_df
    if folds_to_run.empty:
        raise ValueError(f"fold_id={args.fold} no existe en cv_folds (1-{len(folds_df)})")

    for _, fold in folds_to_run.iterrows():
        predictions_df = run_fold(client, fold, dtypes)
        write_fold(client, predictions_df, PREDICTIONS_TABLE, PREDICTIONS_SCHEMA, int(fold["fold_id"]))

    logger.info("Walk-forward LightGBM completo.")


if __name__ == "__main__":
    main()
