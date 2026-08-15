"""
BQML ARIMA_PLUS -- Fase 5, walk-forward CV.

A diferencia del run de referencia de Fase 4b (sql/train_bqml_arima.sql:
30,490 series completas, TRAIN = todo el historial disponible sin ventana
fija, $18.27), este script:

  1. Acota TRAIN a exactamente window_size=365 dias por fold -- igual que
     ARIMA clasico (4a) y LightGBM (4c). INSTRUCCIONES.md (Fase 5) lo exige
     explicitamente: "Aplicar a los 3 modelos con la misma logica y mismo
     tamaño de ventana". El run de 4b (historial completo, sin ventana) no
     cumplia esto -- quedaba bien como dato de referencia aparte (asi se
     documento en su momento), pero no es reutilizable como fold de este
     walk-forward: si se dejara tal cual, BQML veria mas historia que
     ARIMA/LightGBM en cada fold y la comparacion de Fase 6 dejaria de ser
     justa.
  2. Acota las series a m5_dataset.lgbm_sample (~3,000) en vez de las
     30,490 completas -- ver INSTRUCCIONES.md, "Major scope decision":
     Fases 5-9 corren sobre la muestra para mantener el costo de BQML en
     ~$1.80/fold en vez de ~$18/fold.
  3. Entrena contra una tabla PRE-FILTRADA a lgbm_sample
     (sales_long_lgbm_sample, materializada una vez por ensure_source_table()),
     no contra sales_long via JOIN en cada CREATE MODEL. Este es un fix
     critico, no un detalle de estilo: un INNER JOIN contra lgbm_sample en
     el WHERE de cada fold NO reduce los bytes escaneados -- BigQuery debe
     leer la columna completa de sales_long para el rango de fechas (el
     partition pruning por date si funciona) mas alla de que el JOIN
     descarte casi todas las filas despues, porque ese filtro de series
     vive en otra tabla, no en un WHERE literal que CLUSTER BY pueda usar
     para podar bloques. Confirmado en la practica: el primer intento de
     este script (JOIN directo) estimo ~$104 para un solo fold -- casi lo
     mismo que si no se filtrara por muestra en absoluto. La tabla
     pre-filtrada resuelve esto: al ya contener solo las ~3,000 series
     (materializada con un CREATE TABLE AS SELECT de una sola vez, a la
     tarifa NORMAL de BigQuery, no la de BQML), el filtro de fecha por fold
     si poda correctamente sobre una tabla que ya es ~10x mas chica.
  4. Un modelo BQML distinto por fold (baseline_arima_cv_fold{N}) -- ARIMA_
     PLUS no permite reentrenar "in place" con otra ventana bajo el mismo
     nombre sin perder el anterior, y conservarlos separados permite
     inspeccionar cualquier fold despues sin volver a entrenar.

Guardrail de costo: cada CREATE MODEL se lanza primero en dry_run para
loggear una estimacion de costo (bytes escaneados x tarifa BQML time-series
$312.50/TiB x el multiplicador ~30x de auto_arima_max_order=4, documentado
en sql/train_bqml_arima.sql -- esto es una aproximacion, no el costo real:
el dry run no puede anticipar el trabajo interno de auto_arima) y pide
confirmacion interactiva antes de correr el CREATE MODEL de verdad. Un
CREATE MODEL fallido o repetido por error de fechas cuesta dinero real y no
se puede deshacer. Los bytes/costo REALES se loggean despues de cada job
(job.total_bytes_billed), esa es la cifra que hay que mirar para validar
contra el estimado de ~$1.80/fold.

Uso:
    python -m src.models.bqml_arima_cv               # materializa la tabla
                                                       # pre-filtrada (una vez,
                                                       # con confirmacion) y
                                                       # corre los 5 folds
    python -m src.models.bqml_arima_cv --fold 3        # un solo fold
    python -m src.models.bqml_arima_cv --yes           # sin confirmacion interactiva
"""

import argparse
import logging

import pandas as pd
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.evaluation.cv_io import write_fold
from src.evaluation.folds import get_bq_client, get_folds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

SALES_TABLE = f"{PROJECT}.{DATASET}.sales_long"
LGBM_SAMPLE_TABLE = f"{PROJECT}.{DATASET}.lgbm_sample"
SOURCE_TABLE = f"{PROJECT}.{DATASET}.sales_long_lgbm_sample"  # pre-filtrada, ver docstring
SERIES_SEGMENTS_TABLE = f"{PROJECT}.{DATASET}.series_segments"
PREDICTIONS_TABLE = f"{PROJECT}.{DATASET}.bqml_predictions_cv"
METADATA_TABLE = f"{PROJECT}.{DATASET}.bqml_metadata_cv"

# Tarifa NORMAL de queries (no la de BQML) -- se usa para estimar/loggear
# el costo de materializar SOURCE_TABLE, que es un CREATE TABLE AS SELECT
# comun, no un CREATE MODEL.
STANDARD_RATE_USD_PER_TIB = 6.25

AUTO_ARIMA_MAX_ORDER = 4  # igual que 4b -- multiplicador ~30x (vs ~42x default)
HOLIDAY_REGION = "US"
VAL_DAYS = 28

# BQML time-series se cobra a $312.50/TiB (vs $6.25/TiB de queries normales)
BQML_RATE_USD_PER_TIB = 312.50
# OJO -- el multiplicador ~30x documentado en sql/train_bqml_arima.sql
# (auto_arima interno evaluando candidatos) se calibro sobre el run de
# referencia de 4b: 30,490 series, historial completo. Confirmado en la
# practica que NO se sostiene a esta escala -- fold 5 sobre SOURCE_TABLE
# (~3,000 series, ventana de 365 dias) dio dry_run=1.21 GB y bytes_billed
# REAL=1.21 GB, practicamente 1:1, no 30:1. La hipotesis de que el
# multiplicador era una constante fija de auto_arima_max_order=4 era
# incorrecta -- parece escalar con el volumen de datos/series de forma
# mas compleja, no como un factor constante. Se deja en 1 (sin corregir)
# y el estimado pre-flight se marca explicitamente como "minimo, no
# definitivo" -- confiar en el numero REAL post-CREATE MODEL (bytes_billed),
# no en este estimado, para decisiones de presupuesto.
BQML_COST_MULTIPLIER = 1

# z-scores de la normal estandar -- mismo criterio que predict_bqml_arima.sql
# y src/models/arima_baseline.py (Fase 4a), para comparacion consistente.
Z_SCORES = {
    "p05": -1.6448536269514722,
    "p25": -0.6744897501960817,
    "p75": 0.6744897501960817,
    "p95": 1.6448536269514722,
}


def model_name(fold_id: int) -> str:
    return f"{PROJECT}.{DATASET}.baseline_arima_cv_fold{fold_id}"


def build_create_model_sql(fold_id: int) -> str:
    """
    TRAIN acotado a [train_start, train_end] (365 dias, fold-especifico)
    sobre SOURCE_TABLE (ya pre-filtrada a lgbm_sample, ver docstring del
    modulo) -- sin JOIN aca: el filtro de series ya esta resuelto de
    antemano en la materializacion, asi que el partition pruning por date
    funciona sobre una tabla que ya es ~10x mas chica.
    """
    return f"""
        CREATE OR REPLACE MODEL `{model_name(fold_id)}`
        OPTIONS(
          model_type = 'ARIMA_PLUS',
          time_series_timestamp_col = 'date',
          time_series_data_col = 'sales',
          time_series_id_col = ['item_id', 'store_id'],
          holiday_region = '{HOLIDAY_REGION}',
          auto_arima_max_order = {AUTO_ARIMA_MAX_ORDER}
        ) AS
        SELECT item_id, store_id, date, sales
        FROM `{SOURCE_TABLE}`
        WHERE date BETWEEN @train_start AND @train_end
    """


def build_predict_sql(fold_id: int) -> str:
    """
    ML.FORECAST con horizon=28 arranca justo despues del ultimo dia de
    TRAIN del modelo -- coincide con val_start del fold por construccion
    (train_end = val_start - 1), no hace falta filtrar por fecha aca.
    """
    return f"""
        SELECT
          item_id,
          store_id,
          DATE(forecast_timestamp) AS date,
          GREATEST(forecast_value + ({Z_SCORES['p05']}) * standard_error, 0) AS p05,
          GREATEST(forecast_value + ({Z_SCORES['p25']}) * standard_error, 0) AS p25,
          GREATEST(forecast_value, 0)                                       AS p50,
          GREATEST(forecast_value + ({Z_SCORES['p75']}) * standard_error, 0) AS p75,
          GREATEST(forecast_value + ({Z_SCORES['p95']}) * standard_error, 0) AS p95
        FROM ML.FORECAST(
          MODEL `{model_name(fold_id)}`,
          STRUCT({VAL_DAYS} AS horizon, 0.95 AS confidence_level)
        )
    """


def estimate_cost_usd(dry_run_bytes: int) -> float:
    tib = dry_run_bytes / (1024 ** 4)
    return tib * BQML_RATE_USD_PER_TIB * BQML_COST_MULTIPLIER


def dry_run_create_model(client: bigquery.Client, fold_id: int, train_start, train_end) -> int:
    job_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        query_parameters=[
            bigquery.ScalarQueryParameter("train_start", "DATE", train_start),
            bigquery.ScalarQueryParameter("train_end", "DATE", train_end),
        ],
    )
    job = client.query(build_create_model_sql(fold_id), job_config=job_config)
    return job.total_bytes_processed or 0


def confirm(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp == "y"


def run_create_model(client: bigquery.Client, fold_id: int, train_start, train_end) -> None:
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("train_start", "DATE", train_start),
            bigquery.ScalarQueryParameter("train_end", "DATE", train_end),
        ]
    )
    job = client.query(build_create_model_sql(fold_id), job_config=job_config)
    job.result()
    billed_bytes = job.total_bytes_billed or 0
    billed_gb = billed_bytes / 1e9
    # OJO: aca NO se aplica BQML_COST_MULTIPLIER -- total_bytes_billed de un
    # job ya ejecutado es el numero real que BigQuery factura (ya refleja
    # el trabajo interno de auto_arima), a diferencia del dry_run previo
    # (build_create_model_sql sin ejecutar) que si necesita el multiplicador
    # como correccion aproximada porque el dry run no anticipa ese trabajo.
    real_cost = (billed_bytes / (1024 ** 4)) * BQML_RATE_USD_PER_TIB
    logger.info(
        f"  CREATE MODEL fold {fold_id} OK -- {billed_gb:.2f} GB facturados "
        f"(~${real_cost:.2f} real, tarifa BQML time-series $312.50/TiB -- "
        f"verificar contra la consola de billing)"
    )


def run_predict(client: bigquery.Client, fold_id: int) -> pd.DataFrame:
    df = client.query(build_predict_sql(fold_id)).to_dataframe()
    df["fold_id"] = fold_id
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"  ML.FORECAST fold {fold_id}: {len(df)} filas")
    return df


def build_metadata_df(predictions_df: pd.DataFrame, segments_df: pd.DataFrame, fold_id: int) -> pd.DataFrame:
    """
    Espejo de sql/build_bqml_metadata.sql, pero calculado en pandas (una
    unica fila por serie x fold, no por serie x dia) para no lanzar un job
    de BQ extra por fold solo para este join -- segments_df se trae una vez
    en main() y se reutiliza para los 5 folds.
    """
    per_series = predictions_df.drop_duplicates(subset=["item_id", "store_id"])[
        ["item_id", "store_id", "p05"]
    ]
    merged = per_series.merge(segments_df, on=["item_id", "store_id"], how="left")
    merged["fold_id"] = fold_id
    merged["fallo_incertidumbre"] = merged["p05"].isna()
    return merged[
        ["item_id", "store_id", "fold_id", "categoria_zero_rate", "tasa_ceros", "fallo_incertidumbre"]
    ]


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
    bigquery.SchemaField("tasa_ceros", "FLOAT"),
    bigquery.SchemaField("fallo_incertidumbre", "BOOLEAN"),
]


def run_fold(client: bigquery.Client, fold: pd.Series, segments_df: pd.DataFrame, auto_yes: bool) -> None:
    fold_id = int(fold["fold_id"])
    train_start, train_end = fold["train_start"], fold["train_end"]
    val_start, val_end = fold["val_start"], fold["val_end"]

    logger.info(f"--- Fold {fold_id}: TRAIN {train_start}->{train_end}  VAL {val_start}->{val_end} ---")

    dry_bytes = dry_run_create_model(client, fold_id, train_start, train_end)
    est_cost = estimate_cost_usd(dry_bytes)
    logger.info(
        f"  Estimado minimo (dry run, sin garantia -- ver nota de "
        f"BQML_COST_MULTIPLIER): {dry_bytes / 1e9:.2f} GB escaneados -> ~${est_cost:.2f}. "
        f"El numero real se loggea despues del CREATE MODEL."
    )

    if not confirm(f"Confirmar CREATE MODEL fold {fold_id} (>=${est_cost:.2f} estimado minimo)?", auto_yes):
        logger.warning(f"  Fold {fold_id} SALTADO por el usuario.")
        return

    run_create_model(client, fold_id, train_start, train_end)
    predictions_df = run_predict(client, fold_id)

    pred_min, pred_max = predictions_df["date"].min().date(), predictions_df["date"].max().date()
    if pred_min != val_start or pred_max != val_end:
        logger.warning(
            f"  OJO: rango de forecast ({pred_min}->{pred_max}) no coincide "
            f"con VAL del fold ({val_start}->{val_end}) -- revisar antes de usar estos datos."
        )

    metadata_df = build_metadata_df(predictions_df, segments_df, fold_id)

    write_fold(client, predictions_df, PREDICTIONS_TABLE, PREDICTIONS_SCHEMA, fold_id)
    write_fold(client, metadata_df, METADATA_TABLE, METADATA_SCHEMA, fold_id)


def build_source_table_sql() -> str:
    return f"""
        CREATE OR REPLACE TABLE `{SOURCE_TABLE}`
        PARTITION BY date
        CLUSTER BY item_id, store_id
        AS
        SELECT s.item_id, s.store_id, s.date, s.sales
        FROM `{SALES_TABLE}` AS s
        INNER JOIN `{LGBM_SAMPLE_TABLE}` AS sample
          ON s.item_id = sample.item_id AND s.store_id = sample.store_id
    """


def ensure_source_table(client: bigquery.Client, force: bool, auto_yes: bool) -> None:
    """
    Materializa SOURCE_TABLE una sola vez (o si --force-rebuild-source).
    El JOIN va aca -- una unica vez, a la tarifa NORMAL de queries, no la
    de BQML -- para que build_create_model_sql() en cada fold no tenga que
    pagar ese JOIN 5 veces a $312.50/TiB (ver docstring del modulo, el
    hallazgo de los ~$104 estimados para un solo fold con el diseño viejo).
    """
    if not force:
        try:
            table = client.get_table(SOURCE_TABLE)
            logger.info(f"{SOURCE_TABLE} ya existe ({table.num_rows:,} filas) -- se reutiliza tal cual.")
            return
        except NotFound:
            pass

    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    dry_job = client.query(build_source_table_sql(), job_config=job_config)
    dry_bytes = dry_job.total_bytes_processed or 0
    est_cost = (dry_bytes / (1024 ** 4)) * STANDARD_RATE_USD_PER_TIB
    logger.info(
        f"Materializando {SOURCE_TABLE}: {dry_bytes / 1e9:.2f} GB escaneados "
        f"-> ~${est_cost:.2f} (tarifa normal, NO BQML -- esto es un CREATE "
        f"TABLE AS SELECT comun, se paga UNA vez)"
    )

    if not confirm(f"Confirmar materializacion de {SOURCE_TABLE} (~${est_cost:.2f})?", auto_yes):
        raise SystemExit("Materializacion de SOURCE_TABLE cancelada -- no se puede continuar sin ella.")

    job = client.query(build_source_table_sql())
    job.result()
    real_cost = ((job.total_bytes_billed or 0) / (1024 ** 4)) * STANDARD_RATE_USD_PER_TIB
    logger.info(f"  OK -- {(job.total_bytes_billed or 0) / 1e9:.2f} GB facturados (~${real_cost:.2f} real)")


def main() -> None:
    parser = argparse.ArgumentParser(description="BQML ARIMA_PLUS walk-forward CV (Fase 5).")
    parser.add_argument("--fold", type=int, default=None, help="Correr un solo fold_id (1-5)")
    parser.add_argument("--yes", action="store_true", help="Sin confirmacion interactiva por fold")
    parser.add_argument(
        "--force-rebuild-source", action="store_true",
        help="Re-materializar sales_long_lgbm_sample aunque ya exista (p.ej. si lgbm_sample cambio)",
    )
    args = parser.parse_args()

    client = get_bq_client()
    ensure_source_table(client, args.force_rebuild_source, args.yes)

    folds_df = get_folds(client)

    segments_df = client.query(
        f"SELECT item_id, store_id, categoria_zero_rate, tasa_ceros FROM `{SERIES_SEGMENTS_TABLE}`"
    ).to_dataframe()
    logger.info(f"series_segments: {len(segments_df)} series de referencia")

    folds_to_run = folds_df[folds_df["fold_id"] == args.fold] if args.fold else folds_df
    if folds_to_run.empty:
        raise ValueError(f"fold_id={args.fold} no existe en cv_folds (1-{len(folds_df)})")

    for _, fold in folds_to_run.iterrows():
        run_fold(client, fold, segments_df, args.yes)

    logger.info("Walk-forward BQML completo.")


if __name__ == "__main__":
    main()
