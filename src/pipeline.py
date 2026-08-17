"""
pipeline.py — Orquestador Extract -> Transform -> Load
==========================================================
Corre el pipeline de Control de Asistencia end-to-end:
  1. Extrae de la API GeoVictoria (AttendanceBook) y de los Excel de RRHH.
  2. Transforma (aplana, corrige medianoche, clasifica permisos).
  3. Carga a local o a GCS según CLOUD_PROVIDER en .env.

Uso:
    python run_pipeline.py --fecha-inicio 2026-08-01 --fecha-fin 2026-08-14 \
        --empleados 76778453,12345678 \
        --archivo-permisos ./data_samples/HistorialdeSolicitudes.xlsx \
        --archivo-marcaciones ./data_samples/Marcaciones_GeoVictoria.xlsx

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import json
import os
from datetime import date, datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.extract.api_extractor import GeoVictoriaAPIExtractor
from src.extract.file_extractor import ExcelExtractor
from src.transform.transformer import AttendanceTransformer
from src.load.local_loader import LocalLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _build_loader(layer: str, output_dir: str, cloud_provider: str):
    """Construye el loader (local o GCS) para la capa indicada (bronze/silver/gold)."""
    if cloud_provider == "gcp":
        from src.load.gcp_loader import GCSLoader
        return GCSLoader(project_id=os.getenv("GCP_PROJECT_ID"), bucket=os.getenv("GCS_BUCKET"), layer=layer)
    return LocalLoader(output_dir=output_dir, layer=layer)


def _attendance_book_to_bronze_df(users_raw: list[dict]) -> pd.DataFrame:
    """
    Convierte la respuesta cruda de AttendanceBook a un DataFrame apto para Bronze:
    1 fila por colaborador, con el JSON completo tal como llegó de la API (sin
    aplanar ni limpiar) en la columna raw_json — máxima trazabilidad.
    """
    rows = [{"empleado_id": str(u.get("Identifier")), "raw_json": json.dumps(u, ensure_ascii=False)} for u in users_raw]
    return pd.DataFrame(rows)


def _find_latest_excel_in_gcs(bucket_name: str, prefix: str, project_id: str) -> str | None:
    """
    Busca el .xlsx más reciente (por fecha de modificación) bajo un prefijo en
    GCS y lo descarga a /tmp. Convención esperada:
        gs://<bucket>/raw-uploads/permisos/*.xlsx
        gs://<bucket>/raw-uploads/marcaciones/*.xlsx
    RRHH sube el export nuevo ahí (manual); el Job automatizado siempre toma
    el más reciente, sin necesidad de indicar la ruta exacta cada corrida.
    """
    from google.cloud import storage

    client = storage.Client(project=project_id)
    blobs = [b for b in client.list_blobs(bucket_name, prefix=prefix) if b.name.endswith(".xlsx")]
    if not blobs:
        logger.warning(f"No se encontró ningún .xlsx en gs://{bucket_name}/{prefix}")
        return None

    latest = max(blobs, key=lambda b: b.updated)
    local_path = f"/tmp/{os.path.basename(latest.name)}"
    latest.download_to_filename(local_path)
    logger.info(f"✓ Descargado el más reciente: gs://{bucket_name}/{latest.name} (modificado {latest.updated}) → {local_path}")
    return local_path


def _resolve_excel_path(explicit_path: str | None, gcs_prefix: str, cloud_provider: str, bucket: str, project_id: str) -> str | None:
    """Si se pasó una ruta explícita, la usa. Si no y estamos en GCP, busca la más reciente en GCS."""
    if explicit_path:
        return explicit_path
    if cloud_provider == "gcp":
        return _find_latest_excel_in_gcs(bucket, gcs_prefix, project_id)
    return None


def run(
    start_date: date,
    end_date: date,
    user_ids: list[str],
    permisos_file: str | None = None,
    marcaciones_file: str | None = None,
) -> dict:
    """Ejecuta el pipeline completo y devuelve las rutas de los archivos generados."""
    logger.info("=== Pipeline de Control de Asistencia — inicio ===")

    output_dir = os.getenv("OUTPUT_DIR", "./out")
    cloud_provider = os.getenv("CLOUD_PROVIDER", "local")

    # 1. EXTRACT
    raw_data = {}

    base_url = os.getenv("GEOVICTORIA_BASE_URL")
    api_key = os.getenv("GEOVICTORIA_API_KEY")
    api_secret = os.getenv("GEOVICTORIA_API_SECRET")
    if base_url and api_key and api_secret:
        api_extractor = GeoVictoriaAPIExtractor(base_url=base_url, api_key=api_key, api_secret=api_secret)
        raw_data["attendance_book_users"] = api_extractor.extract_attendance_book_batched(start_date, end_date, user_ids)
    else:
        logger.warning("Credenciales de GeoVictoria no configuradas en .env — se omite extracción de API")

    file_extractor = ExcelExtractor()

    permisos_file = _resolve_excel_path(
        permisos_file, "raw-uploads/permisos/", cloud_provider, os.getenv("GCS_BUCKET"), os.getenv("GCP_PROJECT_ID")
    )
    marcaciones_file = _resolve_excel_path(
        marcaciones_file, "raw-uploads/marcaciones/", cloud_provider, os.getenv("GCS_BUCKET"), os.getenv("GCP_PROJECT_ID")
    )

    if permisos_file:
        permisos_df = file_extractor.extract_permisos(permisos_file)
        # Alinea al mismo rango de fechas que la API: conserva solo permisos cuyo
        # periodo se solapa con [start_date, end_date] (empiezan antes de que
        # termine el rango Y terminan después de que empiece).
        before = len(permisos_df)
        permisos_df = permisos_df[
            (permisos_df["fecha_inicio"].dt.date <= end_date) & (permisos_df["fecha_fin"].dt.date >= start_date)
        ]
        logger.info(f"Permisos filtrados a {start_date}→{end_date}: {len(permisos_df):,} de {before:,}")
        raw_data["permisos_excel"] = permisos_df

    if marcaciones_file:
        marcaciones_df = file_extractor.extract_marcaciones(marcaciones_file)
        before = len(marcaciones_df)
        marcaciones_df = marcaciones_df[
            (marcaciones_df["fecha"].dt.date >= start_date) & (marcaciones_df["fecha"].dt.date <= end_date)
        ]
        logger.info(f"Marcaciones filtradas a {start_date}→{end_date}: {len(marcaciones_df):,} de {before:,}")
        raw_data["marcaciones_excel"] = marcaciones_df

    # 2. LANDING BRONZE — se guarda tal cual llega, ANTES de cualquier transformación,
    #    para trazabilidad (poder reprocesar Silver sin volver a llamar a la API/leer Excel).
    bronze_datasets = {}
    if "attendance_book_users" in raw_data:
        bronze_datasets["bronze_marcaciones_api"] = _attendance_book_to_bronze_df(raw_data["attendance_book_users"])
    if "permisos_excel" in raw_data:
        bronze_datasets["bronze_permisos"] = raw_data["permisos_excel"]
    if "marcaciones_excel" in raw_data:
        bronze_datasets["bronze_marcaciones_excel"] = raw_data["marcaciones_excel"]

    if bronze_datasets:
        bronze_loader = _build_loader("bronze", output_dir, cloud_provider)
        bronze_loader.load_all(bronze_datasets, ingestion_date=start_date)
        logger.info(f"✓ Bronze aterrizado: {list(bronze_datasets.keys())}")

    # 3. TRANSFORM
    transformer = AttendanceTransformer()
    transformed = transformer.transform(raw_data)

    # 4. LOAD (Silver)
    silver_loader = _build_loader("silver", output_dir, cloud_provider)
    paths = silver_loader.load_all(transformed, ingestion_date=start_date)

    logger.info(f"=== Pipeline completo === stats={transformed.get('stats')}")
    return paths


if __name__ == "__main__":
    # Ejecución manual rápida (ver run_pipeline.py para uso con argumentos CLI)
    run(
        start_date=date.today(),
        end_date=date.today(),
        user_ids=[],
    )