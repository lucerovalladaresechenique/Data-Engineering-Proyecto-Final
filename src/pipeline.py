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

import os
from datetime import date, datetime

from src.extract.api_extractor import GeoVictoriaAPIExtractor
from src.extract.file_extractor import ExcelExtractor
from src.transform.transformer import AttendanceTransformer
from src.load.local_loader import LocalLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run(
    start_date: date,
    end_date: date,
    user_ids: list[str],
    permisos_file: str | None = None,
    marcaciones_file: str | None = None,
) -> dict:
    """Ejecuta el pipeline completo y devuelve las rutas de los archivos generados."""
    logger.info("=== Pipeline de Control de Asistencia — inicio ===")

    # 1. EXTRACT
    raw_data = {}

    base_url = os.getenv("GEOVICTORIA_BASE_URL")
    api_key = os.getenv("GEOVICTORIA_API_KEY")
    api_secret = os.getenv("GEOVICTORIA_API_SECRET")
    if base_url and api_key and api_secret:
        api_extractor = GeoVictoriaAPIExtractor(base_url=base_url, api_key=api_key, api_secret=api_secret)
        raw_data["attendance_book_users"] = api_extractor.extract_attendance_book(start_date, end_date, user_ids)
    else:
        logger.warning("Credenciales de GeoVictoria no configuradas en .env — se omite extracción de API")

    file_extractor = ExcelExtractor()
    if permisos_file:
        raw_data["permisos_excel"] = file_extractor.extract_permisos(permisos_file)
    if marcaciones_file:
        raw_data["marcaciones_excel"] = file_extractor.extract_marcaciones(marcaciones_file)

    # 2. TRANSFORM
    transformer = AttendanceTransformer()
    transformed = transformer.transform(raw_data)

    # 3. LOAD
    output_dir = os.getenv("OUTPUT_DIR", "./out")
    cloud_provider = os.getenv("CLOUD_PROVIDER", "local")

    if cloud_provider == "gcp":
        from src.load.gcp_loader import GCSLoader
        loader = GCSLoader(
            project_id=os.getenv("GCP_PROJECT_ID"),
            bucket=os.getenv("GCS_BUCKET"),
            layer="silver",
        )
    else:
        loader = LocalLoader(output_dir=output_dir, layer="silver")

    paths = loader.load_all(transformed, ingestion_date=start_date)

    logger.info(f"=== Pipeline completo === stats={transformed.get('stats')}")
    return paths


if __name__ == "__main__":
    # Ejecución manual rápida (ver run_pipeline.py para uso con argumentos CLI)
    run(
        start_date=date.today(),
        end_date=date.today(),
        user_ids=[],
    )
