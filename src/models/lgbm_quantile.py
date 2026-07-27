"""
LightGBM Quantile -- Fase 4c, smoke test.

Entrena 5 modelos independientes (uno por percentil P5/P25/P50/P75/P95,
objective='quantile') sobre m5_dataset.features_train, filtrado a
m5_dataset.lgbm_sample (~3,000 series, muestra proporcional -- no las
30,490 completas; ver sql/build_lgbm_sample.sql), con hiperparametros
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

Manejo de memoria (e2-standard-4, 16GB RAM): TRAIN (~1.1M filas con
lgbm_sample, ~10% del volumen de las 30,490 series completas) y VAL (~84K
filas) se traen con dos queries separadas, nunca combinadas en memoria a
la vez, y las columnas FLOAT64 se piden directo como float32 via el
parametro dtypes de to_dataframe() -- evita el pico de memoria de
materializar todo en float64 para despues downcastear. train_df se libera
explicitamente (del + gc.collect()) antes de traer val_df. Esta reduccion
de memoria se penso para las 30,490 series completas y a esta escala
(~1.1M filas) probablemente ya no sea necesaria, pero se deja tal cual
hasta confirmar que corre bien. Este mismo patron lo reutilizara Fase 5 en
cada fold del walk-forward.

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
LGBM_SAMPLE_TABLE = f"{PROJECT}.{DATASET}.lgbm_sample"
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

# Downcast explicito de columnas INT64 de bajo rango -- BigQuery las tipa
# genericamente como INTEGER (8 bytes), pero su rango real cabe en 1-2
# bytes. int8/int16 de numpy, NO los nullable Int8/Int16 de pandas -- estos
# ultimos tienen antecedentes de ser rechazados por LightGBM
# (_get_bad_pandas_dtypes) y no vale la pena arriesgar un ValueError.
# Solo se piden directo en el dtypes de to_dataframe() las columnas que
# nunca traen NULL (deterministicas, derivadas de la fecha); year excede el
# rango de int8 (valores 2011-2016) por eso usa int16. price_changed y
# snap_active SI pueden traer NULL (ver build_features_train.sql) y se
# manejan aparte: se dejan en su dtype default (float64, ya soporta NaN sin
# problema) y se rellenan con un centinela -1 + astype('int8') en
# cast_categoricals(), antes del cast a category.
INT_DOWNCAST_DTYPES = {
    "day_of_week": "int8",
    "day_of_month": "int8",
    "month": "int8",
    "year": "int16",
    "week_of_year": "int8",
    "is_event": "int8",
    "is_christmas": "int8",
}

# Columnas categoricas que pueden traer NULL -- se rellenan con este
# centinela y se bajan a int8 en cast_categoricals(), en vez de pedirse
# directo como int8 en el dtypes de to_dataframe() (fallaria: numpy int8
# no soporta NaN).
NULLABLE_INT_SENTINEL_COLS = ["price_changed", "snap_active"]
SENTINEL_VALUE = -1


def get_reduced_memory_dtypes(client: bigquery.Client) -> dict[str, str]:
    """
    Mapa {columna: dtype} para pedirle a to_dataframe() que descargue ya
    reducido: columnas FLOAT64 -> float32 (lags, rolling stats, Fourier,
    precio -- el grueso de las ~50 columnas) y las INT64 de bajo rango sin
    NULL de INT_DOWNCAST_DTYPES -> int8/int16. client.get_table() es
    metadata pura, no escanea datos ni cuesta.
    """
    table = client.get_table(FEATURES_TABLE)
    float_dtypes = {field.name: "float32" for field in table.schema if field.field_type in ("FLOAT", "FLOAT64")}
    return {**float_dtypes, **INT_DOWNCAST_DTYPES}


def _fetch_features_window(
    client: bigquery.Client,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    dtypes: dict[str, str],
    label: str,
    exclude_id_cols: bool = False,
) -> pd.DataFrame:
    """
    Trae features_train filtrado a [start, end_exclusive) -- ventana abierta
    a la derecha para que TRAIN y VAL se puedan pedir con dos queries
    separadas sin traslapar ni dejar huecos en el corte (val_start) -- y
    tambien filtrado a las series de lgbm_sample (~3,000, muestra
    proporcional; ver sql/build_lgbm_sample.sql), no las 30,490 completas.

    dtypes pide las columnas ya reducidas (float32 / int8 / int16) en la
    conversion Arrow -> pandas, evitando el pico de memoria de traer todo
    en float64/int64 para downcastear despues.

    exclude_id_cols=True (usado para TRAIN) hace SELECT * EXCEPT (item_id,
    store_id) -- esas dos columnas ya se excluyen como features en
    train_models(), asi que no tiene sentido cargarlas para las ~1.1M filas
    de TRAIN. VAL si las necesita (identifican las predicciones de salida).
    """
    select_clause = "* EXCEPT (item_id, store_id)" if exclude_id_cols else "*"
    query = f"""
        SELECT {select_clause}
        FROM `{FEATURES_TABLE}`
        WHERE date >= @start AND date < @end_exclusive
          AND STRUCT(item_id, store_id) IN (
            SELECT STRUCT(item_id, store_id) FROM `{LGBM_SAMPLE_TABLE}`
          )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start.date()),
            bigquery.ScalarQueryParameter("end_exclusive", "DATE", end_exclusive.date()),
        ]
    )
    df = client.query(query, job_config=job_config).to_dataframe(dtypes=dtypes)
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

    price_changed/snap_active llegan en su dtype default (float64, puede
    traer NaN) -- se rellenan con el centinela SENTINEL_VALUE (-1, fuera
    del rango real 0/1) y se bajan a int8 antes del cast a category, para
    no depender de los tipos nullable Int8/Int16 de pandas.
    """
    for col in NULLABLE_INT_SENTINEL_COLS:
        df[col] = df[col].fillna(SENTINEL_VALUE).astype("int8")
    df[CATEGORICAL_COLS] = df[CATEGORICAL_COLS].astype("category")
    return df


def train_models(train_df: pd.DataFrame) -> dict[str, lgb.Booster]:
    feature_cols = [c for c in train_df.columns if c not in EXCLUDE_COLS]
    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COL]

    os.makedirs(MODEL_DIR, exist_ok=True)

    # Un solo Dataset, construido una vez y reutilizado para los 5
    # lgb.train() (alpha es el unico param que cambia entre quantiles, no
    # afecta el binning) -- evita reconstruir el binning 5 veces sobre las
    # mismas ~1.1M filas. free_raw_data=True (default real de LightGBM, no
    # el False anterior) libera la copia interna de los datos crudos que el
    # Dataset mantendria despues de construct(); aca no hace falta, el
    # train_set no se vuelve a reconstruir ni a re-etiquetar.
    logger.info("Construyendo Dataset de entrenamiento (una sola vez para los 5 quantiles)...")
    train_set = lgb.Dataset(X_train, label=y_train, free_raw_data=True)
    train_set.construct()

    boosters = {}
    for q_name, alpha in QUANTILE_LEVELS.items():
        params = {**BASE_PARAMS, "objective": "quantile", "alpha": alpha}

        logger.info(f"Entrenando modelo {q_name} (alpha={alpha})...")
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
    dtypes = get_reduced_memory_dtypes(client)

    # TRAIN y VAL se traen y liberan por separado -- nunca coexisten en
    # memoria las ~1.18M filas combinadas (lgbm_sample), solo ~1.1M y
    # luego ~84K. TRAIN excluye item_id/store_id (exclude_id_cols=True):
    # ya se excluyen como features en train_models(), no hace falta cargarlas.
    train_df = _fetch_features_window(
        client, train_start, val_start, dtypes, label="train", exclude_id_cols=True
    )
    train_df = cast_categoricals(train_df)
    boosters = train_models(train_df)

    del train_df
    gc.collect()

    # VAL si necesita item_id/store_id -- identifican las predicciones de salida.
    val_df = _fetch_features_window(
        client, val_start, val_end + pd.Timedelta(days=1), dtypes, label="val", exclude_id_cols=False
    )
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
