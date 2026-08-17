"""
gold_pipeline.py — Orquestador de la capa Gold
====================================================
Lee las tablas Silver ya generadas (Parquet local o GCS) y produce las
tablas Gold: fact_asistencia_diaria, fact_ausentismo, dim_empleado, dim_turno.

Se ejecuta como un paso separado del pipeline de Bronze/Silver (coincide con
el diagrama: Sources -> Extract -> Bronze -> Transform -> Silver -> Gold,
orquestado por Cloud Composer como pasos independientes).

Uso:
    python run_gold_pipeline.py --fecha 2026-08-14

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import os
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.transform.gold_transformer import GoldTransformer
from src.load.local_loader import LocalLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _read_silver_table_local(output_dir: str, table_name: str, ingestion_date: date) -> pd.DataFrame:
    """Lee un Parquet de Silver desde disco local. Si no existe, devuelve DataFrame vacío."""
    path = Path(output_dir) / "silver" / table_name / f"ingestion_date={ingestion_date.isoformat()}" / "data.parquet"
    if not path.exists():
        logger.warning(f"No se encontró {path} — se continúa con DataFrame vacío para {table_name}")
        return pd.DataFrame()
    df = pd.read_parquet(path)
    logger.info(f"Leído {table_name}: {len(df):,} filas ← {path}")
    return df


def _read_silver_table_gcs(project_id: str, bucket: str, table_name: str, ingestion_date: date) -> pd.DataFrame:
    """Lee un Parquet de Silver desde GCS (descarga en memoria, sin archivo temporal)."""
    import io
    from google.cloud import storage
    from google.api_core.exceptions import NotFound

    blob_name = f"silver/{table_name}/ingestion_date={ingestion_date.isoformat()}/data.parquet"
    gcs_uri = f"gs://{bucket}/{blob_name}"

    client = storage.Client(project=project_id)
    blob = client.bucket(bucket).blob(blob_name)

    buffer = io.BytesIO()
    try:
        blob.download_to_file(buffer)
    except NotFound:
        logger.warning(f"No se encontró {gcs_uri} — se continúa con DataFrame vacío para {table_name}")
        return pd.DataFrame()

    buffer.seek(0)
    df = pd.read_parquet(buffer)
    logger.info(f"Leído {table_name}: {len(df):,} filas ← {gcs_uri}")
    return df


def _read_silver_table(output_dir: str, table_name: str, ingestion_date: date, cloud_provider: str) -> pd.DataFrame:
    if cloud_provider == "gcp":
        return _read_silver_table_gcs(
            project_id=os.getenv("GCP_PROJECT_ID"),
            bucket=os.getenv("GCS_BUCKET"),
            table_name=table_name,
            ingestion_date=ingestion_date,
        )
    return _read_silver_table_local(output_dir, table_name, ingestion_date)


def run_gold(ingestion_date: date, output_dir: str | None = None) -> dict:
    logger.info("=== Pipeline Gold — inicio ===")
    output_dir = output_dir or os.getenv("OUTPUT_DIR", "./out")
    cloud_provider = os.getenv("CLOUD_PROVIDER", "local")
    logger.info(f"Leyendo Silver desde: {'GCS' if cloud_provider == 'gcp' else 'disco local'}")

    marcaciones_df = _read_silver_table(output_dir, "silver_marcaciones_excel", ingestion_date, cloud_provider)
    turnos_df = _read_silver_table(output_dir, "silver_turnos", ingestion_date, cloud_provider)
    ausencias_df = _read_silver_table(output_dir, "silver_ausencias", ingestion_date, cloud_provider)

    gt = GoldTransformer()
    gold = gt.build(marcaciones_df=marcaciones_df, turnos_df=turnos_df, ausencias_df=ausencias_df)

    cloud_provider = os.getenv("CLOUD_PROVIDER", "local")
    if cloud_provider == "gcp":
        from src.load.bq_loader import BQLoader
        loader = BQLoader(project_id=os.getenv("GCP_PROJECT_ID"), dataset_id=os.getenv("BQ_DATASET", "gold"))
        paths = loader.load_all(gold)
    else:
        loader = LocalLoader(output_dir=output_dir, layer="gold")
        paths = loader.load_all(gold, ingestion_date=ingestion_date)
    logger.info(f"=== Pipeline Gold completo === stats={gold.get('stats')}")
    return paths


if __name__ == "__main__":
    run_gold(ingestion_date=date.today())