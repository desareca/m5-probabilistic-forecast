"""
Reshape M5 sales_wide → sales_long en BigQuery
Estrategia: UNION ALL en batches de N días para evitar
            "too many subqueries or query is too complex"

Primer batch: CREATE OR REPLACE TABLE (define schema + partición)
Batches siguientes: INSERT INTO
"""

from google.cloud import bigquery

# ── Configuración ─────────────────────────────────────────────────────────────
PROJECT      = "mle-m5-forecast"
DATASET      = "m5_dataset"
SOURCE_TABLE = f"`{PROJECT}.{DATASET}.sales_wide`"
DEST_TABLE   = f"`{PROJECT}.{DATASET}.sales_long`"
START_DATE   = "2011-01-29"   # d_1
BATCH_SIZE   = 100            # días por job — ajustar si sigue fallando


def get_actual_day_columns(client: bigquery.Client) -> list[str]:
    """
    Lee el schema real de la tabla para obtener solo las columnas d_N
    que existen, en orden numérico.
    """
    table_ref = f"{PROJECT}.{DATASET}.sales_wide"
    table = client.get_table(table_ref)
    day_cols = sorted(
        [f.name for f in table.schema if f.name.startswith("d_")],
        key=lambda c: int(c.split("_")[1])
    )
    return day_cols


def build_batch_sql(day_cols: list[str], day_offset_map: dict[str, int],
                    is_first: bool) -> str:
    """
    Genera CREATE OR REPLACE TABLE (primer batch) o INSERT INTO (resto).
    day_offset_map: {col_name: days_since_start}
    """
    selects = []
    for col, offset in day_offset_map.items():
        selects.append(
        f"  SELECT\n"
        f"    id,\n"
        f"    CONCAT(SPLIT(id, '_')[OFFSET(0)], '_', SPLIT(id, '_')[OFFSET(1)], '_', SPLIT(id, '_')[OFFSET(2)]) AS item_id,\n"
        f"    CONCAT(SPLIT(id, '_')[OFFSET(3)], '_', SPLIT(id, '_')[OFFSET(4)]) AS store_id,\n"
        f"    DATE_ADD(DATE('{START_DATE}'), INTERVAL {offset} DAY) AS date,\n"
        f"    CAST(`{col}` AS INT64) AS sales\n"
        f"  FROM {SOURCE_TABLE}\n"
        f"  WHERE `{col}` IS NOT NULL"
        )

    union_body = "\nUNION ALL\n".join(selects)

    if is_first:
        return (
            f"CREATE OR REPLACE TABLE {DEST_TABLE}\n"
            f"PARTITION BY date\n"
            f"CLUSTER BY item_id, store_id\n"
            f"AS\n"
            f"SELECT * FROM (\n{union_body}\n);\n"
        )
    else:
        return (
            f"INSERT INTO {DEST_TABLE}\n"
            f"SELECT * FROM (\n{union_body}\n);\n"
        )


def run():
    client = bigquery.Client(project=PROJECT)

    print("Leyendo schema de sales_wide...")
    day_cols = get_actual_day_columns(client)
    n_days   = len(day_cols)
    n_batches = (n_days + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Columnas de día encontradas : {n_days}")
    print(f"Batch size                  : {BATCH_SIZE} días")
    print(f"Total de jobs a ejecutar    : {n_batches}")
    print(f"Destino                     : {DEST_TABLE}\n")

    # Construir mapa col → offset (días desde START_DATE)
    first_day_num = int(day_cols[0].split("_")[1])  # normalmente 1
    col_offset = {col: int(col.split("_")[1]) - first_day_num for col in day_cols}

    total_rows = 0

    for batch_idx in range(n_batches):
        batch_cols = day_cols[batch_idx * BATCH_SIZE : (batch_idx + 1) * BATCH_SIZE]
        batch_map  = {col: col_offset[col] for col in batch_cols}
        is_first   = (batch_idx == 0)

        day_start = batch_cols[0]
        day_end   = batch_cols[-1]
        print(f"[{batch_idx + 1}/{n_batches}] {day_start} → {day_end}  ({len(batch_cols)} días)...")

        sql = build_batch_sql(day_cols, batch_map, is_first)

        job = client.query(sql)
        result = job.result()  # bloquea hasta completar

        affected = job.num_dml_affected_rows or 0
        total_rows += affected
        gb = (job.total_bytes_processed or 0) / 1e9
        print(f"         ✓  filas={affected:,}  bytes={gb:.2f} GB  job={job.job_id}")

    print(f"\n{'='*60}")
    print(f"✓ Reshape completo")
    print(f"  Total filas escritas : {total_rows:,}")
    print(f"  Tabla               : {DEST_TABLE}")


if __name__ == "__main__":
    run()
