"""
Load M5 dataset from GCS to BigQuery.

This script:
1. Reads CSVs from GCS (sales_train_validation, sell_prices, calendar)
2. Loads them to BigQuery in their original format (wide for sales)
3. Creates tables: sales_wide, sell_prices, calendar
"""

import os
import logging
from google.cloud import bigquery
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT", "mle-m5-forecast")
DATASET_ID = "m5_dataset"
BUCKET_NAME = f"{PROJECT_ID}-m5-bucket"


def upload_to_gcs(local_path: str, bucket_name: str, blob_name: str) -> str:
    """Upload file to GCS and return gs:// URI."""
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    logger.info(f"Uploading {local_path} to gs://{bucket_name}/{blob_name}")
    blob.upload_from_filename(local_path)

    gcs_uri = f"gs://{bucket_name}/{blob_name}"
    logger.info(f"Uploaded to {gcs_uri}")
    return gcs_uri


def load_csv_to_bigquery(
    gcs_uri: str,
    dataset_id: str,
    table_id: str,
    skip_leading_rows: int = 1,
    max_bad_records: int = 0,
) -> None:
    """Load CSV from GCS to BigQuery table."""
    bq_client = bigquery.Client(project=PROJECT_ID)

    job_config = bigquery.LoadJobConfig(
        skip_leading_rows=skip_leading_rows,
        max_bad_records=max_bad_records,
        source_format=bigquery.SourceFormat.CSV,
        autodetect=True,
    )

    destination_table = f"{PROJECT_ID}.{dataset_id}.{table_id}"
    logger.info(f"Loading {gcs_uri} to {destination_table}")

    load_job = bq_client.load_table_from_uri(
        gcs_uri, destination_table, job_config=job_config
    )
    load_job.result()  # Wait for job to complete

    destination_table = bq_client.get_table(destination_table)
    logger.info(f"Loaded {destination_table.num_rows} rows to {destination_table.project}.{destination_table.dataset_id}.{destination_table.table_id}")


def load_m5_data(data_dir: str) -> None:
    """
    Load M5 dataset to BigQuery.

    Args:
        data_dir: Local directory containing M5 CSVs
    """
    files_to_load = [
        ("sales_train_validation.csv", "sales_wide"),
        ("sell_prices.csv", "sell_prices"),
        ("calendar.csv", "calendar"),
    ]

    for csv_file, table_id in files_to_load:
        local_path = os.path.join(data_dir, csv_file)

        if not os.path.exists(local_path):
            logger.warning(f"File not found: {local_path}")
            continue

        # Upload to GCS
        gcs_uri = upload_to_gcs(local_path, BUCKET_NAME, f"raw/{csv_file}")

        # Load to BigQuery
        load_csv_to_bigquery(gcs_uri, DATASET_ID, table_id)

        logger.info(f"✓ Successfully loaded {csv_file} to {table_id}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = "data/raw"

    load_m5_data(data_dir)
    logger.info("All data loaded successfully!")
