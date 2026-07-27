"""
LightGBM Quantile -- Fase 4c, smoke test.

Entrena 5 modelos independientes (uno por percentil P5/P25/P50/P75/P95,
objective='quantile') sobre m5_dataset.features_train, con hiperparametros
fijos y sin early stopping -- smoke test simple y deterministico, no el
walk-forward completo (eso lo hace Fase 5 reutilizando esta misma logica).

Mismo esquema temporal que 4a/4b: TRAIN = 365 dias inmediatamente antes de
VAL, VAL = ultimos 28 dias disponibles (calculado sobre MAX(date) real).
Reutiliza fetch_date_window() de arima_baseline.py para que los tres
modelos corran exactamente sobre el mismo fold.

item_id y store_id se excluyen de las features (el modelo debe generalizar
desde señales derivadas, no memorizar la serie -- ver INSTRUCCIONES.md,
Fase 4c). Los NULLs de lag/rolling al inicio de cada serie no se imputan;
LightGBM los maneja nativamente.

Quantile crossing: los 5 valores predichos por fila se ordenan (np.sort)
antes de guardar, garantizando monotonicidad P5 <= P25 <= P50 <= P75 <= P95.

Uso:
    python -m src.models.lgbm_quantile
"""

import logging
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from google.cloud import bigquery

from src.models.arima_baseline import (
    DATASET,
    PROJECT,
    QUANTILE_LEVELS,
    fetch_date_window,
    get_bq_client,
    write_to_bigquery,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FEATURES_TABLE = f"{PROJECT}.{DATASET}.features_train"
PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.predictions_lgbm"

MODEL_DIR = "models/lgbm_quantile"

# Columnas que el modelo no debe ver: item_id/store_id (Fase 4c, generalizar
# desde señales derivadas, no memorizar la serie), date (no es una feature
# utilizable directamente -- days_since_start ya sirve de proxy de tendencia)
# y sales (target).
EXCLUDE_COLS = ["item_id", "store_id", "date", "sales"]
TARGET_COL = "sales"

# Cast a category dtype de pandas antes de entrenar -- especificacion
# literal de INSTRUCCIONES.md, Fase 4c.
CATEGORICAL_COLS = [
    "day_of_week",
    "day_of_month",
    "month",
    "week_of_year",
    "event_type",
    "is_event",
    "is_christmas",
    "snap_active",
    "price_changed",
]

# Hiperparametros fijos, sin early stopping (Fase 4 = smoke test simple y
# deterministico; Fase 5 puede agregar ajuste fino despues). n_estimators
# es alias reconocido de num_iterations en LightGBM, tanto en la API
# sklearn como en la nativa (lgb.train) -- se puede pasar tal cual en params.
BASE_PARAMS = {
    "n_estimators": 1000,
    "learning_rate": 0.05,
    "num_leaves": 127,
    "verbosity": -1,
}


def fetch_features(client: bigquery.Client, train_start: pd.Timestamp, val_end: pd.Timestamp) -> pd.DataFrame:
    """
    Trae features_train filtrado a [train_start, val_end] en una sola query.
    Tamaño esperado: 365 dias x 30,490 series (~11.1M filas de train) + 28
    dias x 30,490 series (~853K filas de VAL) = ~11.98M filas totales.
    """
    query = f"""
        SELECT *
        FROM `{FEATURES_TABLE}`
        WHERE date BETWEEN @train_start AND @val_end
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("train_start", "DATE", train_start.date()),
            bigquery.ScalarQueryParameter("val_end", "DATE", val_end.date()),
        ]
    )
    df = client.query(query, job_config=job_config).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"features_train (ventana train+val): {len(df)} filas, {df.shape[1]} columnas")
    return df


def cast_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Castea CATEGORICAL_COLS a category dtype sobre el DataFrame combinado
    (train+val juntos, antes de separar) -- si se castea por separado, train
    y val pueden terminar con distintos conjuntos de categorias y desalinear
    los codigos categoricos entre fit() y predict(). No esta explicito en
    INSTRUCCIONES.md; es la forma correcta de evitar ese desajuste.
    """
    df = df.copy()
    df[CATEGORICAL_COLS] = df[CATEGORICAL_COLS].astype("category")
    return df


def train_and_predict(train_df: pd.DataFrame, val_df: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [c for c in train_df.columns if c not in EXCLUDE_COLS]

    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COL]
    X_val = val_df[feature_cols]

    os.makedirs(MODEL_DIR, exist_ok=True)

    preds = {}
    for q_name, alpha in QUANTILE_LEVELS.items():
        params = {**BASE_PARAMS, "objective": "quantile", "alpha": alpha}

        logger.info(f"Entrenando modelo {q_name} (alpha={alpha})...")
        train_set = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
        booster = lgb.train(params, train_set)

        model_path = os.path.join(MODEL_DIR, f"lgbm_{q_name}.txt")
        booster.save_model(model_path)
        logger.info(f"  -> guardado en {model_path}")

        # clip(0, None): mismo criterio que 4a/4b -- evita cuantiles
        # negativos en series de ventas bajas/intermitentes.
        preds[q_name] = np.clip(booster.predict(X_val), 0, None)

    quantile_names = list(QUANTILE_LEVELS.keys())
    preds_matrix = np.column_stack([preds[q] for q in quantile_names])

    # Quantile crossing: ordena los 5 valores por fila para garantizar
    # monotonicidad P5 <= P25 <= P50 <= P75 <= P95.
    preds_sorted = np.sort(preds_matrix, axis=1)

    predictions_df = val_df[["item_id", "store_id", "date"]].reset_index(drop=True).copy()
    predictions_df[quantile_names] = preds_sorted
    return predictions_df


def run_lgbm_quantile() -> pd.DataFrame:
    client = get_bq_client()

    train_start, val_start, val_end = fetch_date_window(client)
    df = fetch_features(client, train_start, val_end)
    df = cast_categoricals(df)

    train_df = df[df["date"] < val_start]
    val_df = df[df["date"] >= val_start]
    logger.info(f"train_df: {len(train_df)} filas, val_df: {len(val_df)} filas")

    return train_and_predict(train_df, val_df)


def main() -> None:
    client = get_bq_client()
    predictions_df = run_lgbm_quantile()

    schema = [
        bigquery.SchemaField("item_id", "STRING"),
        bigquery.SchemaField("store_id", "STRING"),
        bigquery.SchemaField("date", "DATE"),
        bigquery.SchemaField("p05", "FLOAT"),
        bigquery.SchemaField("p25", "FLOAT"),
        bigquery.SchemaField("p50", "FLOAT"),
        bigquery.SchemaField("p75", "FLOAT"),
        bigquery.SchemaField("p95", "FLOAT"),
    ]
    write_to_bigquery(client, predictions_df, PREDICTIONS_TABLE, schema)


if __name__ == "__main__":
    main()
