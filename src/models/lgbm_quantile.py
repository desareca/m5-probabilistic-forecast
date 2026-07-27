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

Manejo de memoria (e2-standard-4, 16GB RAM): TRAIN (~11.1M filas) y VAL
(~853K filas) se traen con dos queries separadas, nunca combinadas en
memoria a la vez, y las columnas FLOAT64 se piden directo como float32 via
el parametro dtypes de to_dataframe() -- evita el pico de memoria de
materializar todo en float64 para despues downcastear. train_df se libera
explicitamente (del + gc.collect()) antes de traer val_df. Este mismo
patron lo reutilizara Fase 5 en cada fold del walk-forward.

Uso:
    python -m src.models.lgbm_quantile
"""

import gc
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


def get_float32_dtypes(client: bigquery.Client) -> dict[str, str]:
    """
    Mapa {columna: 'float32'} para todas las columnas FLOAT64 de
    features_train (lags, rolling stats, Fourier, features de precio --
    la mayoria de las ~50 columnas y el grueso del peso en memoria).
    client.get_table() es metadata pura, no escanea datos ni cuesta.
    """
    table = client.get_table(FEATURES_TABLE)
    return {field.name: "float32" for field in table.schema if field.field_type in ("FLOAT", "FLOAT64")}


def _fetch_features_window(
    client: bigquery.Client,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    float_dtypes: dict[str, str],
    label: str,
) -> pd.DataFrame:
    """
    Trae features_train filtrado a [start, end_exclusive) -- ventana abierta
    a la derecha para que TRAIN y VAL se puedan pedir con dos queries
    separadas sin traslapar ni dejar huecos en el corte (val_start).

    dtypes=float_dtypes pide las columnas FLOAT64 directo como float32 en
    la conversion Arrow -> pandas, evitando el pico de memoria de traer
    todo en float64 para downcastear despues.
    """
    query = f"""
        SELECT *
        FROM `{FEATURES_TABLE}`
        WHERE date >= @start AND date < @end_exclusive
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start.date()),
            bigquery.ScalarQueryParameter("end_exclusive", "DATE", end_exclusive.date()),
        ]
    )
    df = client.query(query, job_config=job_config).to_dataframe(dtypes=float_dtypes)
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"features_train ({label}): {len(df)} filas, {df.shape[1]} columnas")
    return df


def cast_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Castea CATEGORICAL_COLS a category dtype in-place (sin copiar el
    DataFrame -- ya es bastante grande). Train y val se castean por
    separado, cada uno con su propio fetch; no hace falta que compartan el
    mismo set de categorias porque LightGBM no usa el dtype 'category' del
    DataFrame de prediccion tal cual -- el Booster guarda en memoria
    (atributo pandas_categorical) las categorias vistas en el train_set y
    remapea los codigos de cualquier DataFrame que se le pase a predict()
    contra esa lista, no contra las categorias propias del DataFrame de
    val. Esto solo es valido porque aqui se predice con el Booster recien
    entrenado en el mismo proceso -- si en Fase 5/6 se recarga un modelo
    guardado desde disco (Booster(model_file=...)) para predecir en un
    proceso separado, pandas_categorical no se serializa y habria que
    resolver el alineamiento de categorias explicitamente en ese momento.
    """
    df[CATEGORICAL_COLS] = df[CATEGORICAL_COLS].astype("category")
    return df


def train_models(train_df: pd.DataFrame) -> dict[str, lgb.Booster]:
    feature_cols = [c for c in train_df.columns if c not in EXCLUDE_COLS]
    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COL]

    os.makedirs(MODEL_DIR, exist_ok=True)

    boosters = {}
    for q_name, alpha in QUANTILE_LEVELS.items():
        params = {**BASE_PARAMS, "objective": "quantile", "alpha": alpha}

        logger.info(f"Entrenando modelo {q_name} (alpha={alpha})...")
        train_set = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
        booster = lgb.train(params, train_set)

        model_path = os.path.join(MODEL_DIR, f"lgbm_{q_name}.txt")
        booster.save_model(model_path)
        logger.info(f"  -> guardado en {model_path}")

        boosters[q_name] = booster

    return boosters


def predict_quantiles(boosters: dict[str, lgb.Booster], val_df: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [c for c in val_df.columns if c not in EXCLUDE_COLS]
    X_val = val_df[feature_cols]

    preds = {}
    for q_name, booster in boosters.items():
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
    float_dtypes = get_float32_dtypes(client)

    # TRAIN y VAL se traen y liberan por separado -- nunca coexisten en
    # memoria las ~11.98M filas combinadas, solo ~11.1M y luego ~853K.
    train_df = _fetch_features_window(client, train_start, val_start, float_dtypes, label="train")
    train_df = cast_categoricals(train_df)
    boosters = train_models(train_df)

    del train_df
    gc.collect()

    val_df = _fetch_features_window(client, val_start, val_end + pd.Timedelta(days=1), float_dtypes, label="val")
    val_df = cast_categoricals(val_df)
    predictions_df = predict_quantiles(boosters, val_df)

    del val_df
    gc.collect()

    return predictions_df


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
