"""
gcp_loader.py — Carga a Google Cloud Storage (GCP)
======================================================
Sube DataFrames transformados a GCS en formato Parquet, respetando la
convención de particionado del proyecto (ingestion_date, no year/month/day).

Prerequisitos:
  1. pip install google-cloud-storage
  2. Autenticación: GOOGLE_APPLICATION_CREDENTIALS, gcloud auth application-default
     login, o Service Account adjunto (recomendado en Cloud Run / Composer).

Arquitectura: API/Excel → extractor → transformer → GCS (bronze/silver) → BigQuery (gold)

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import io
from datetime import date

import pandas as pd

try:
    from google.cloud import storage
    from google.api_core.exceptions import NotFound, Forbidden
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GCSLoader:
    """
    Carga DataFrames a GCS como Parquet.

    Args:
        project_id: ID del proyecto GCP.
        bucket:     Nombre del bucket GCS.
        layer:      Capa del lakehouse: "bronze" | "silver" | "gold".

    Convención de paths en GCS:
        gs://<bucket>/<layer>/<table_name>/ingestion_date=2026-08-14/data.parquet
    """

    def __init__(self, project_id: str, bucket: str, layer: str = "silver"):
        if not GCS_AVAILABLE:
            raise ImportError("google-cloud-storage no está instalado.\nEjecuta: pip install google-cloud-storage")

        self.project_id = project_id
        self.bucket_name = bucket
        self.layer = layer

        self._client = storage.Client(project=self.project_id)
        self._bucket = self._get_bucket()
        logger.info(f"GCSLoader → gs://{self.bucket_name}/{self.layer}/ [{self.project_id}]")

    def _get_bucket(self):
        try:
            bucket = self._client.get_bucket(self.bucket_name)
            logger.info(f"✓ Conectado a GCS bucket: {self.bucket_name}")
            return bucket
        except NotFound:
            raise ValueError(
                f"Bucket '{self.bucket_name}' no encontrado en proyecto '{self.project_id}'.\n"
                "Créalo con: gsutil mb -p <project_id> gs://<bucket_name>"
            )
        except Forbidden:
            raise PermissionError(
                f"Sin permisos para acceder a gs://{self.bucket_name}.\n"
                "Verifica que la cuenta de servicio tenga el rol 'Storage Object Admin'."
            )

    def _build_blob_name(self, table_name: str, ingestion_date: date) -> str:
        return f"{self.layer}/{table_name}/ingestion_date={ingestion_date.isoformat()}/data.parquet"

    def load(self, df: pd.DataFrame, table_name: str, ingestion_date: date | None = None) -> str:
        ingestion_date = ingestion_date or date.today()
        blob_name = self._build_blob_name(table_name, ingestion_date)
        gcs_uri = f"gs://{self.bucket_name}/{blob_name}"

        logger.info(f"Subiendo {len(df):,} registros → {gcs_uri}")
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, compression="snappy", engine="pyarrow")
        buffer.seek(0)

        blob = self._bucket.blob(blob_name)
        blob.metadata = {"table_name": table_name, "record_count": str(len(df)), "uploaded_by": "asistencia-etl"}
        blob.upload_from_file(buffer, content_type="application/octet-stream")

        size_kb = buffer.tell() / 1024
        logger.info(f"✓ Subido: {gcs_uri} ({size_kb:.1f} KB)")
        return gcs_uri

    def load_all(self, transformed_data: dict, ingestion_date: date | None = None) -> dict[str, str]:
        tables = {k: v for k, v in transformed_data.items() if isinstance(v, pd.DataFrame)}
        uris = {name: self.load(df, name, ingestion_date) for name, df in tables.items()}
        logger.info(f"✓ {len(uris)} tablas subidas a GCS")
        return uris
