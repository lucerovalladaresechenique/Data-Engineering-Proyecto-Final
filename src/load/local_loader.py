"""
local_loader.py — Carga a almacenamiento local
==================================================
Guarda los DataFrames transformados en disco como Parquet, respetando
la convención de particionado del proyecto:
    {output_dir}/{layer}/{table_name}/ingestion_date=YYYY-MM-DD/data.parquet

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

from datetime import date
from pathlib import Path

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class LocalLoader:
    """
    Persiste DataFrames en el sistema de archivos local.

    Args:
        output_dir: Carpeta raíz de salida (ej. "./out").
        layer:      Capa del lakehouse: "bronze" | "silver" | "gold".

    Ejemplo:
        loader = LocalLoader(output_dir="./out", layer="silver")
        loader.load(silver_marcaciones_df, "silver_marcaciones")
    """

    def __init__(self, output_dir: str = "./out", layer: str = "silver"):
        self.output_dir = Path(output_dir)
        self.layer = layer

    def load(self, df: pd.DataFrame, table_name: str, ingestion_date: date | None = None) -> Path:
        ingestion_date = ingestion_date or date.today()
        partition_dir = self.output_dir / self.layer / table_name / f"ingestion_date={ingestion_date.isoformat()}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        file_path = partition_dir / "data.parquet"
        logger.info(f"Guardando {len(df):,} registros → {file_path}")
        df.to_parquet(file_path, index=False, compression="snappy")

        size_kb = file_path.stat().st_size / 1024
        logger.info(f"✓ {file_path.name} guardado ({size_kb:.1f} KB)")
        return file_path

    def load_all(self, transformed_data: dict, ingestion_date: date | None = None) -> dict[str, Path]:
        tables = {k: v for k, v in transformed_data.items() if isinstance(v, pd.DataFrame)}
        return {name: self.load(df, name, ingestion_date) for name, df in tables.items()}
