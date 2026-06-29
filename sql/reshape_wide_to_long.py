"""
Reshape M5 sales_wide → sales_long en BigQuery
Estrategia: UNION ALL estático (1 SELECT por día)
BigQuery lo paraleliza automáticamente, sin costos de JSON ni CROSS JOIN.

Requisitos:
    pip install google-cloud-bigquery
    Autenticación: gcloud auth application-default login
"""

from google.cloud import bigquery

# ── Configuración ─────────────────────────────────────────────────────────────
PROJECT      = "mle-m5-forecast"
DATASET      = "m5_dataset"
SOURCE_TABLE = f"{PROJECT}.{DATASET}.sales_wide"
DEST_TABLE   = f"{PROJECT}.{DATASET}.sales_long"
N_DAYS       = 1913
START_DATE   = "2011-01-29"   # d_1 = 2011-01-29

# ── Construcción del SQL ───────────────────────────────────────────────────────
def build_union_sql(source: str, dest: str, n_days: int, start_date: str) -> str:
    """
    Genera un CREATE OR REPLACE TABLE con UNION ALL de n_days SELECTs.
    Cada SELECT extrae una columna d_N y calcula la fecha correspondiente.
    """
    selects = []
    for d in range(1, n_days + 1):
        col = f"d_{d}"
        selects.append(
            f"  SELECT\n"
            f"    id,\n"
            f"    REGEXP_SUBSTR(id, r'^[^_]+')  AS item_id,\n"
            f"    REGEXP_SUBSTR(id, r'[^_]+$')  AS store_id,\n"
            f"    DATE_ADD(DATE('{start_date}'), INTERVAL {d - 1} DAY) AS date,\n"
            f"    CAST(`{col}` AS INT64) AS sales\n"
            f"  FROM `{source}`\n"
            f"  WHERE `{col}` IS NOT NULL"
        )

    union_body = "\n\nUNION ALL\n\n".join(selects)

    sql = (
        f"CREATE OR REPLACE TABLE `{dest}`\n"
        f"PARTITION BY date\n"             # particionar por fecha → queries posteriores más baratos
        f"CLUSTER BY item_id, store_id\n"  # clustering → filtros por item/store mucho más rápidos
        f"OPTIONS (require_partition_filter = FALSE)\n"
        f"AS\n"
        f"{union_body}\n"
    )
    return sql


# ── Ejecución ─────────────────────────────────────────────────────────────────
def run(dry_run: bool = False):
    """
    dry_run=True  → solo imprime el SQL (primeros 3 bloques + resumen)
    dry_run=False → ejecuta en BigQuery
    """
    sql = build_union_sql(SOURCE_TABLE, DEST_TABLE, N_DAYS, START_DATE)

    if dry_run:
        # Muestra los primeros 2 bloques y el último para validar
        blocks = sql.split("UNION ALL")
        print("=== PRIMEROS 2 BLOQUES ===")
        print("UNION ALL".join(blocks[:2]))
        print(f"\n... ({N_DAYS - 3} bloques omitidos) ...\n")
        print("=== ÚLTIMO BLOQUE ===")
        print(blocks[-1])
        print(f"\nTotal de bloques UNION ALL: {N_DAYS}")
        print(f"Tamaño aproximado del SQL: {len(sql) / 1_000:.0f} KB")
        return

    # Guardar SQL generado (útil para auditoría)
    sql_path = "reshape_generated.sql"
    with open(sql_path, "w") as f:
        f.write(sql)
    print(f"SQL guardado en {sql_path} ({len(sql) / 1_000:.0f} KB)")

    # Ejecutar en BigQuery
    client = bigquery.Client(project=PROJECT)

    job_config = bigquery.QueryJobConfig(
        # Sin límite de bytes: esta query procesa ~59M filas, es esperado
        allow_large_results=True,
        use_legacy_sql=False,
    )

    print(f"Ejecutando reshape: {SOURCE_TABLE} → {DEST_TABLE}")
    print(f"Días: {N_DAYS} | Filas estimadas: ~{30_490 * N_DAYS / 1_000_000:.0f}M")
    print("Iniciando job en BigQuery...")

    job = client.query(sql, job_config=job_config)

    print(f"Job ID: {job.job_id}")
    print("Esperando resultado (puede tomar varios minutos)...")

    result = job.result()  # bloquea hasta completar

    print(f"\n✓ Completado.")
    print(f"  Filas escritas : {job.num_dml_affected_rows or 'N/A (DDL)'}")
    print(f"  Bytes procesados: {job.total_bytes_processed / 1e9:.2f} GB")
    print(f"  Slot ms usados  : {job.slot_millis}")
    print(f"  Tabla destino   : {DEST_TABLE}")


if __name__ == "__main__":
    import sys

    # Uso:
    #   python generate_reshape_sql.py          → ejecuta en BQ
    #   python generate_reshape_sql.py --dry    → solo muestra SQL
    dry = "--dry" in sys.argv
    run(dry_run=dry)