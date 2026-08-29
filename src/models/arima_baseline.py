"""
ARIMA clasico (statsmodels via pmdarima.auto_arima) -- Fase 4a, smoke test.

Ajusta un ARIMA por serie (auto_arima, seasonal=False, sin fallback a naive)
sobre las 32 series de m5_dataset.arima_sample, y deriva cuantiles P5/P25/
P50/P75/P95 asumiendo normalidad sobre el forecast + error estandar.

Esquema temporal (igual al que usara el walk-forward de Fase 5, fold mas
reciente): TRAIN = 365 dias inmediatamente antes de VAL, VAL = ultimos 28
dias disponibles en sales_long. No busca escalar a las 30,490 series --
eso lo cubre BQML ARIMA_PLUS (Fase 4b); el objetivo aqui es exponer el
mecanismo de auto_arima y por que falla en series intermitentes.

No hay fallback silencioso: una serie que no converge o que produce
varianza de residuos ~0 (degenerada) se marca como fallo con la razon
especifica -- el fallo en si es un hallazgo del experimento (ver resumen
impreso al final de main()).

Uso:
    python -m src.models.arima_baseline
"""

import logging
import warnings

import numpy as np
import pandas as pd
import pmdarima as pm
from google.cloud import bigquery
from scipy.stats import norm
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from src.common import DATASET, PROJECT, QUANTILE_LEVELS, get_bq_client, write_to_bigquery  # noqa: F401 -- re-exportados, ver src/common.py

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_TABLE = f"{PROJECT}.{DATASET}.arima_sample"
SALES_TABLE = f"{PROJECT}.{DATASET}.sales_long"
PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.arima_predictions"
METADATA_TABLE = f"{PROJECT}.{DATASET}.arima_metadata"

TRAIN_DAYS = 365
VAL_DAYS = 28

# Rangos acotados para auto_arima -- no busqueda exhaustiva (seasonal=False:
# ver INSTRUCCIONES.md Fase 4a, la estacionalidad la exploran Fourier/BQML).
# suppress_warnings=False es deliberado: la deteccion de ConvergenceWarning
# en fit_and_forecast() depende de que estos warnings efectivamente se
# emitan durante el fit -- el log de consola sera mas ruidoso, pero ese
# ruido es la senal que este script necesita capturar.
AUTO_ARIMA_KWARGS = dict(
    seasonal=False,
    max_p=5,
    max_q=5,
    max_d=2,
    stepwise=True,
    suppress_warnings=False,
    error_action="ignore",
    # default de statsmodels/pmdarima es maxiter=50 -- insuficiente para el
    # solver L-BFGS-B con series de 365 puntos y ordenes de hasta (5,2,5):
    # mas parametros a estimar y una superficie de verosimilitud mas
    # compleja necesitan mas iteraciones para asentar, no indican una serie
    # genuinamente problematica. 200 da 4x margen sin ocultar series que
    # realmente no convergen (esas seguiran fallando incluso con mas
    # iteraciones -- el objetivo es dejar de confundir "necesita mas pasos"
    # con "no converge").
    maxiter=200,
)

# Umbral de varianza de residuos por debajo del cual el modelo se considera
# degenerado (comun en series muy_lento donde auto_arima puede converger a
# un modelo que predice ~constante con residuos ~0).
DEGENERATE_VARIANCE_THRESHOLD = 1e-6


def fetch_sample_metadata(client: bigquery.Client) -> pd.DataFrame:
    """Las 32 series de arima_sample: item_id, store_id, categoria_zero_rate."""
    query = f"""
        SELECT item_id, store_id, categoria_zero_rate
        FROM `{SAMPLE_TABLE}`
    """
    df = client.query(query).to_dataframe()
    logger.info(f"arima_sample: {len(df)} series")
    return df


def fetch_date_window(client: bigquery.Client) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """
    Calcula los cortes de fecha sobre el rango completo de sales_long:
    VAL = ultimos VAL_DAYS dias disponibles; TRAIN = los TRAIN_DAYS
    inmediatamente anteriores a VAL. Mismo esquema que reutilizara Fase 5
    como primer fold del walk-forward.
    """
    query = f"SELECT MAX(date) AS max_date FROM `{SALES_TABLE}`"
    max_date = pd.Timestamp(client.query(query).to_dataframe()["max_date"].iloc[0])

    val_start = max_date - pd.Timedelta(days=VAL_DAYS - 1)
    train_start = val_start - pd.Timedelta(days=TRAIN_DAYS)
    train_end = val_start - pd.Timedelta(days=1)

    logger.info(f"TRAIN: {train_start.date()} -> {train_end.date()} ({TRAIN_DAYS} dias)")
    logger.info(f"VAL:   {val_start.date()} -> {max_date.date()} ({VAL_DAYS} dias)")
    return train_start, val_start, max_date


def fetch_sample_series(
    client: bigquery.Client, train_start: pd.Timestamp, val_end: pd.Timestamp
) -> pd.DataFrame:
    """
    Trae en una sola query la serie diaria (date, sales) de las 32 series
    de la muestra, acotada a [train_start, val_end] -- evita 32 queries
    individuales.
    """
    query = f"""
        SELECT s.item_id, s.store_id, s.date, s.sales
        FROM `{SALES_TABLE}` s
        INNER JOIN `{SAMPLE_TABLE}` sample
          ON s.item_id = sample.item_id AND s.store_id = sample.store_id
        WHERE s.date BETWEEN @train_start AND @val_end
        ORDER BY s.item_id, s.store_id, s.date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("train_start", "DATE", train_start.date()),
            bigquery.ScalarQueryParameter("val_end", "DATE", val_end.date()),
        ]
    )
    df = client.query(query, job_config=job_config).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"sales_long (muestra, ventana train+val): {len(df)} filas")
    return df


def fit_and_forecast(train_sales: np.ndarray, val_dates: pd.DatetimeIndex) -> dict:
    """
    Ajusta auto_arima sobre train_sales y, si converge y no es degenerado,
    genera forecast + cuantiles para cada fecha de val_dates.

    Retorna un dict con las columnas de metadata (p, d, q, aic, convergio,
    razon_fallo) y, si convergio, un DataFrame de cuantiles por fecha
    (None si fallo).
    """
    result = {
        "p": None,
        "d": None,
        "q": None,
        "aic": None,
        "convergio": False,
        "razon_fallo": None,
        "quantiles_df": None,
    }

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            model = pm.auto_arima(train_sales, **AUTO_ARIMA_KWARGS)
            convergence_warnings = [w for w in caught if issubclass(w.category, ConvergenceWarning)]
    except Exception as e:
        result["razon_fallo"] = f"auto_arima exception: {e}"
        return result

    order = model.order
    result["p"], result["d"], result["q"] = order
    result["aic"] = float(model.aic())

    if convergence_warnings:
        result["razon_fallo"] = f"no convergio: {convergence_warnings[0].message}"
        return result

    mle_retvals = getattr(model.arima_res_, "mle_retvals", None)
    if isinstance(mle_retvals, dict) and mle_retvals.get("converged") is False:
        result["razon_fallo"] = "no convergio: mle_retvals.converged=False"
        return result

    resid = np.asarray(model.arima_res_.resid)
    resid_var = float(np.nanvar(resid))
    if not np.isfinite(resid_var) or resid_var < DEGENERATE_VARIANCE_THRESHOLD:
        result["razon_fallo"] = f"modelo degenerado: varianza de residuos = {resid_var:.2e}"
        return result

    forecast_res = model.arima_res_.get_forecast(steps=len(val_dates))
    mean = np.asarray(forecast_res.predicted_mean)
    se = np.asarray(forecast_res.se_mean)

    quantiles = {
        name: np.clip(norm.ppf(level, loc=mean, scale=se), 0, None)
        for name, level in QUANTILE_LEVELS.items()
    }
    quantiles_df = pd.DataFrame({"date": val_dates, **quantiles})

    result["convergio"] = True
    result["quantiles_df"] = quantiles_df
    return result


def run_arima_baseline() -> tuple[pd.DataFrame, pd.DataFrame]:
    client = get_bq_client()

    sample_df = fetch_sample_metadata(client)
    train_start, val_start, val_end = fetch_date_window(client)
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
            f"[{i + 1}/{len(sample_df)}] {item_id} / {store_id} "
            f"(categoria_zero_rate={categoria_zero_rate}, n_train={len(train_sales)})"
        )

        fit_result = fit_and_forecast(train_sales, val_dates)

        metadata_rows.append(
            {
                "item_id": item_id,
                "store_id": store_id,
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
            predictions_rows.append(q_df)
        else:
            logger.warning(f"  -> FALLO: {fit_result['razon_fallo']}")

    metadata_df = pd.DataFrame(metadata_rows)
    predictions_df = (
        pd.concat(predictions_rows, ignore_index=True)[
            ["item_id", "store_id", "date", "p05", "p25", "p50", "p75", "p95"]
        ]
        if predictions_rows
        else pd.DataFrame(columns=["item_id", "store_id", "date", "p05", "p25", "p50", "p75", "p95"])
    )

    return predictions_df, metadata_df


def print_convergence_summary(metadata_df: pd.DataFrame) -> None:
    """
    Hallazgo central del experimento: cuantas de las 32 series convergieron
    vs fallaron, desglosado por categoria_zero_rate.
    """
    summary = (
        metadata_df.groupby("categoria_zero_rate")["convergio"]
        .agg(n_series="count", n_convergio="sum")
        .assign(n_fallo=lambda d: d["n_series"] - d["n_convergio"])
        .reindex(["rapido", "medio", "lento", "muy_lento"])
    )
    logger.info("Resumen de convergencia por categoria_zero_rate:\n%s", summary.to_string())

    fallos = metadata_df[~metadata_df["convergio"]][["item_id", "store_id", "categoria_zero_rate", "razon_fallo"]]
    if not fallos.empty:
        logger.info("Detalle de fallos:\n%s", fallos.to_string(index=False))


def main() -> None:
    client = get_bq_client()
    predictions_df, metadata_df = run_arima_baseline()

    predictions_schema = [
        bigquery.SchemaField("item_id", "STRING"),
        bigquery.SchemaField("store_id", "STRING"),
        bigquery.SchemaField("date", "DATE"),
        bigquery.SchemaField("p05", "FLOAT"),
        bigquery.SchemaField("p25", "FLOAT"),
        bigquery.SchemaField("p50", "FLOAT"),
        bigquery.SchemaField("p75", "FLOAT"),
        bigquery.SchemaField("p95", "FLOAT"),
    ]
    metadata_schema = [
        bigquery.SchemaField("item_id", "STRING"),
        bigquery.SchemaField("store_id", "STRING"),
        bigquery.SchemaField("categoria_zero_rate", "STRING"),
        bigquery.SchemaField("p", "INTEGER"),
        bigquery.SchemaField("d", "INTEGER"),
        bigquery.SchemaField("q", "INTEGER"),
        bigquery.SchemaField("aic", "FLOAT"),
        bigquery.SchemaField("convergio", "BOOLEAN"),
        bigquery.SchemaField("razon_fallo", "STRING"),
    ]

    write_to_bigquery(client, predictions_df, PREDICTIONS_TABLE, predictions_schema)
    write_to_bigquery(client, metadata_df, METADATA_TABLE, metadata_schema)

    print_convergence_summary(metadata_df)


if __name__ == "__main__":
    main()
