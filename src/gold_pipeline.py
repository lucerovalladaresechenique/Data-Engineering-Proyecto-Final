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

from src.transform.gold_transformer import GoldTransformer
from src.load.local_loader import LocalLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _read_silver_table(output_dir: str, table_name: str, ingestion_date: date) -> pd.DataFrame:
    """Lee un Parquet de Silver ya escrito por src/pipeline.py. Si no existe, devuelve DataFrame vacío."""
    path = Path(output_dir) / "silver" / table_name / f"ingestion_date={ingestion_date.isoformat()}" / "data.parquet"
    if not path.exists():
        logger.warning(f"No se encontró {path} — se continúa con DataFrame vacío para {table_name}")
        return pd.DataFrame()
    df = pd.read_parquet(path)
    logger.info(f"Leído {table_name}: {len(df):,} filas ← {path}")
    return df


def run_gold(ingestion_date: date, output_dir: str | None = None) -> dict:
    logger.info("=== Pipeline Gold — inicio ===")
    output_dir = output_dir or os.getenv("OUTPUT_DIR", "./out")

    marcaciones_df = _read_silver_table(output_dir, "silver_marcaciones_excel", ingestion_date)
    turnos_df = _read_silver_table(output_dir, "silver_turnos", ingestion_date)
    ausencias_df = _read_silver_table(output_dir, "silver_ausencias", ingestion_date)

    gt = GoldTransformer()
    gold = gt.build(marcaciones_df=marcaciones_df, turnos_df=turnos_df, ausencias_df=ausencias_df)

    cloud_provider = os.getenv("CLOUD_PROVIDER", "local")
    if cloud_provider == "gcp":
        from src.load.gcp_loader import GCSLoader
        loader = GCSLoader(project_id=os.getenv("GCP_PROJECT_ID"), bucket=os.getenv("GCS_BUCKET"), layer="gold")
    else:
        loader = LocalLoader(output_dir=output_dir, layer="gold")

    paths = loader.load_all(gold, ingestion_date=ingestion_date)
    logger.info(f"=== Pipeline Gold completo === stats={gold.get('stats')}")
    return paths


if __name__ == "__main__":
    run_gold(ingestion_date=date.today())
