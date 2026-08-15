"""
Definicion de folds para walk-forward CV -- Fase 5.

Genera 5 folds fijos espaciados (no las ~54 posibles con paso de 28 dias --
descartado por costo/tiempo, ver phase-summaries/04-modelos.md) sobre el
rango real de fechas de m5_dataset.sales_long. Cada fold usa exactamente
el mismo esquema temporal que el smoke test de Fase 4:
  TRAIN = 365 dias inmediatamente antes de VAL
  VAL   = 28 dias

El fold 5 (el mas reciente) coincide por construccion con el fold ya
corrido en Fase 4 (arima_predictions, predictions_lgbm) -- mismo
VAL_start = MAX(date) - 27, mismo TRAIN_start = VAL_start - 365. No hace
falta re-correr ARIMA (4a) ni LightGBM (4c) para ese fold. BQML (4b) SI
se re-corre para fold 5, porque el run de Fase 4 fue sobre las 30,490
series completas y Fase 5 acota BQML a lgbm_sample (ver INSTRUCCIONES.md,
"Major scope decision").

Espaciado de folds 1-4: uniforme entre el primer VAL_start posible
(MIN(date) + TRAIN_DAYS, primer punto con 365 dias de historia previa) y
el VAL_start del fold 5 (MAX(date) - VAL_DAYS + 1). Fechas de folds nunca
hardcodeadas -- se calculan desde MIN/MAX(date) real de sales_long, igual
que fetch_date_window() en arima_baseline.py.

Uso:
    python -m src.evaluation.folds              # imprime folds, no escribe
    python -m src.evaluation.folds --write       # ademas escribe cv_folds
"""

import argparse
import logging

import pandas as pd
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = "mle-m5-forecast"
DATASET = "m5_dataset"

SALES_TABLE = f"{PROJECT}.{DATASET}.sales_long"
FOLDS_TABLE = f"{PROJECT}.{DATASET}.cv_folds"

TRAIN_DAYS = 365
VAL_DAYS = 28
N_FOLDS = 5


def get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


def fetch_date_bounds(client: bigquery.Client) -> tuple[pd.Timestamp, pd.Timestamp]:
    """MIN/MAX(date) real de sales_long -- nunca hardcodear el rango."""
    query = f"SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM `{SALES_TABLE}`"
    row = client.query(query).to_dataframe().iloc[0]
    min_date, max_date = pd.Timestamp(row["min_date"]), pd.Timestamp(row["max_date"])
    logger.info(f"sales_long: {min_date.date()} -> {max_date.date()}")
    return min_date, max_date


def generate_folds(
    min_date: pd.Timestamp,
    max_date: pd.Timestamp,
    train_days: int = TRAIN_DAYS,
    val_days: int = VAL_DAYS,
    n_folds: int = N_FOLDS,
) -> pd.DataFrame:
    """
    5 folds espaciados uniformemente. fold_id=N_FOLDS coincide exactamente
    con el esquema del smoke test de Fase 4 (ver docstring del modulo).
    """
    val_start_last = max_date - pd.Timedelta(days=val_days - 1)
    val_start_first = min_date + pd.Timedelta(days=train_days)

    if val_start_first > val_start_last:
        raise ValueError(
            f"Rango de fechas insuficiente para {n_folds} folds de "
            f"{train_days}+{val_days} dias: primer VAL_start posible "
            f"({val_start_first.date()}) es posterior al del ultimo fold "
            f"({val_start_last.date()})."
        )

    span_days = (val_start_last - val_start_first).days
    step = span_days / (n_folds - 1) if n_folds > 1 else 0

    rows = []
    for i in range(n_folds):
        fold_id = i + 1
        if fold_id == n_folds:
            # Ultimo fold: exacto, sin redondeo -- debe coincidir bit a bit
            # con el fold ya corrido en Fase 4.
            val_start = val_start_last
        else:
            val_start = val_start_first + pd.Timedelta(days=round(step * i))

        train_start = val_start - pd.Timedelta(days=train_days)
        train_end = val_start - pd.Timedelta(days=1)
        val_end = val_start + pd.Timedelta(days=val_days - 1)

        rows.append(
            {
                "fold_id": fold_id,
                "train_start": train_start.date(),
                "train_end": train_end.date(),
                "val_start": val_start.date(),
                "val_end": val_end.date(),
            }
        )

    folds_df = pd.DataFrame(rows)

    # Chequeo de no-solapamiento entre VAL windows consecutivas -- si esto
    # dispara, el dataset es mas corto de lo esperado para 5 folds de este
    # tamano y hay que revisar train_days/val_days/n_folds, no ignorarlo.
    overlaps = (
        pd.to_datetime(folds_df["val_start"]).shift(-1)
        <= pd.to_datetime(folds_df["val_end"])
    )
    if overlaps.iloc[:-1].any():
        logger.warning("VAL windows de folds consecutivos se solapan -- revisar espaciado.")

    return folds_df


def write_folds_table(client: bigquery.Client, folds_df: pd.DataFrame) -> None:
    """
    Escribe cv_folds como tabla de referencia -- Fase 6 la usa para hacer
    JOIN por fold_id al comparar metricas entre modelos. WRITE_TRUNCATE:
    cv_folds siempre refleja la ultima definicion de folds, no se acumula.
    """
    schema = [
        bigquery.SchemaField("fold_id", "INTEGER"),
        bigquery.SchemaField("train_start", "DATE"),
        bigquery.SchemaField("train_end", "DATE"),
        bigquery.SchemaField("val_start", "DATE"),
        bigquery.SchemaField("val_end", "DATE"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    load_job = client.load_table_from_dataframe(folds_df, FOLDS_TABLE, job_config=job_config)
    load_job.result()
    logger.info(f"Escritas {len(folds_df)} filas en {FOLDS_TABLE}")


def get_folds(client: bigquery.Client) -> pd.DataFrame:
    """Punto de entrada para arima_baseline.py / lgbm_quantile.py / BQML:
    trae bounds reales y genera los 5 folds, sin tocar BigQuery en escritura."""
    min_date, max_date = fetch_date_bounds(client)
    return generate_folds(min_date, max_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera los 5 folds de walk-forward CV.")
    parser.add_argument(
        "--write", action="store_true", help="Ademas de imprimir, escribe m5_dataset.cv_folds"
    )
    args = parser.parse_args()

    client = get_bq_client()
    folds_df = get_folds(client)

    logger.info("Folds generados:\n%s", folds_df.to_string(index=False))

    fold5 = folds_df.iloc[-1]
    logger.info(
        f"Verificacion fold {N_FOLDS} (debe coincidir con el smoke test de Fase 4): "
        f"TRAIN {fold5['train_start']} -> {fold5['train_end']}, "
        f"VAL {fold5['val_start']} -> {fold5['val_end']}"
    )

    if args.write:
        write_folds_table(client, folds_df)
    else:
        logger.info("No se escribio cv_folds (usar --write para persistir).")


if __name__ == "__main__":
    main()
