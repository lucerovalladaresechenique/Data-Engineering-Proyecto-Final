"""
bq_loader.py — Carga de la capa Gold a BigQuery
====================================================
Sube las tablas Gold (fact_asistencia_diaria, fact_ausentismo, dim_empleado,
dim_turno) a BigQuery, en vez de dejarlas como Parquet en GCS — coincide con
la arquitectura de referencia (Serving/Gold: BigQuery, ver architecture.md).

Prerequisitos:
  1. pip install google-cloud-bigquery
  2. Crear el dataset una vez:
     bq mk --dataset --location=US-CENTRAL1 <project_id>:<dataset_id>
  3. La cuenta de servicio necesita los roles "BigQuery Data Editor" y
     "BigQuery Job User" (a nivel de proyecto o del dataset).

Simplificación actual: cada corrida REEMPLAZA la tabla completa
(write_disposition=WRITE_TRUNCATE), no hace append incremental. Para un
pipeline productivo con múltiples fechas, se recomienda particionar por
`fecha`/`ingestion_date` y usar WRITE_APPEND — queda como mejora futura.

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import pandas as pd

try:
    from google.cloud import bigquery
    from google.api_core.exceptions import NotFound, Forbidden
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BQLoader:
    """
    Carga DataFrames a BigQuery como tablas (reemplazo completo por corrida).

    Args:
        project_id: ID del proyecto GCP.
        dataset_id: Dataset de BigQuery donde viven las tablas Gold (ej. "gold").

    Ejemplo:
        loader = BQLoader(project_id="proyecto-final-505619", dataset_id="gold")
        loader.load(fact_asistencia_diaria_df, "fact_asistencia_diaria")
    """

    def __init__(self, project_id: str, dataset_id: str):
        if not BQ_AVAILABLE:
            raise ImportError("google-cloud-bigquery no está instalado.\nEjecuta: pip install google-cloud-bigquery")

        self.project_id = project_id
        self.dataset_id = dataset_id
        self._client = bigquery.Client(project=self.project_id)
        logger.info(f"BQLoader → {self.project_id}.{self.dataset_id} [BigQuery]")

    def load(self, df: pd.DataFrame, table_name: str) -> str:
        table_id = f"{self.project_id}.{self.dataset_id}.{table_name}"
        logger.info(f"Subiendo {len(df):,} registros → {table_id}")

        # BigQuery no acepta columnas datetime con timezone-naive de forma directa
        # en todos los casos; se normaliza a tipos compatibles antes de subir.
        df_clean = df.copy()
        for col in df_clean.select_dtypes(include=["datetime64[ns]"]).columns:
            df_clean[col] = pd.to_datetime(df_clean[col], errors="coerce")

        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            autodetect=True,
        )

        try:
            job = self._client.load_table_from_dataframe(df_clean, table_id, job_config=job_config)
            job.result()  # espera a que termine
        except NotFound:
            raise ValueError(
                f"Dataset '{self.dataset_id}' no encontrado en proyecto '{self.project_id}'.\n"
                f"Créalo con: bq mk --dataset --location=US-CENTRAL1 {self.project_id}:{self.dataset_id}"
            )
        except Forbidden:
            raise PermissionError(
                f"Sin permisos para escribir en {table_id}.\n"
                "Verifica que la cuenta de servicio tenga los roles "
                "'BigQuery Data Editor' y 'BigQuery Job User'."
            )

        table = self._client.get_table(table_id)
        logger.info(f"✓ {table.num_rows:,} filas en {table_id}")
        return table_id

    def load_all(self, transformed_data: dict, **kwargs) -> dict[str, str]:
        tables = {k: v for k, v in transformed_data.items() if isinstance(v, pd.DataFrame)}
        table_ids = {name: self.load(df, name) for name, df in tables.items()}
        logger.info(f"✓ {len(table_ids)} tablas cargadas a BigQuery")
        return table_ids