"""
run_daily.py — Punto de entrada para ejecución automatizada (Cloud Run Job).

Corre el pipeline completo (Bronze -> Silver -> Gold) para UN día, pensado
para dispararse diariamente vía Cloud Scheduler + Cloud Run Job.

Por defecto procesa el día ANTERIOR (ayer) — patrón típico de batch diario:
se corre en la madrugada y procesa el día que acaba de cerrar.

La parte de la API (marcas + turnos) es 100% automatizable, sin intervención
humana. Los Excel de RRHH (permisos, marcaciones) son opcionales aquí porque
dependen de que alguien los exporte de GeoVictoria — si se montan/incluyen en
la imagen, también se procesan; si no, el pipeline sigue solo con la API.

Variables de entorno:
    FECHA               YYYY-MM-DD (opcional, default: ayer)
    EMPLEADOS_FILE      ruta al .txt de IDs (default: empleados.txt en la imagen)
    ARCHIVO_PERMISOS    ruta al Excel de permisos (opcional)
    ARCHIVO_MARCACIONES ruta al Excel de marcaciones (opcional)
"""
import os
from datetime import date, timedelta

from src.pipeline import run
from src.gold_pipeline import run_gold
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _get_fecha() -> date:
    fecha_str = os.getenv("FECHA")
    if fecha_str:
        return date.fromisoformat(fecha_str)
    return date.today() - timedelta(days=1)


def main():
    fecha = _get_fecha()
    empleados_file = os.getenv("EMPLEADOS_FILE", "empleados.txt")
    permisos_file = os.getenv("ARCHIVO_PERMISOS")
    marcaciones_file = os.getenv("ARCHIVO_MARCACIONES")

    if not os.path.exists(empleados_file):
        raise FileNotFoundError(
            f"No se encontró {empleados_file}. Genera la lista con: "
            f"python list_empleados.py <excel_marcaciones> — o incluye el archivo en la imagen Docker."
        )

    with open(empleados_file) as f:
        user_ids = [line.strip() for line in f if line.strip()]

    logger.info(f"=== Ejecución automatizada — fecha: {fecha} | {len(user_ids)} empleados ===")
    if not permisos_file and not marcaciones_file:
        logger.info("Sin archivos Excel montados — corriendo solo con datos de la API (esperado en automatización).")

    run(
        start_date=fecha,
        end_date=fecha,
        user_ids=user_ids,
        permisos_file=permisos_file,
        marcaciones_file=marcaciones_file,
    )
    run_gold(ingestion_date=fecha)
    logger.info("=== Ejecución automatizada completa ===")


if __name__ == "__main__":
    main()