"""
run_pipeline.py — Punto de entrada CLI del pipeline.

Uso:
    python run_pipeline.py \
        --fecha-inicio 2026-08-01 --fecha-fin 2026-08-14 \
        --empleados 76778453,12345678 \
        --archivo-permisos ./data_samples/HistorialdeSolicitudes.xlsx \
        --archivo-marcaciones ./data_samples/Marcaciones_GeoVictoria.xlsx
"""
import argparse
from datetime import datetime

from src.pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Pipeline de Control de Asistencia (GeoVictoria)")
    parser.add_argument("--fecha-inicio", required=True, help="YYYY-MM-DD")
    parser.add_argument("--fecha-fin", required=True, help="YYYY-MM-DD")
    parser.add_argument("--empleados", default="", help="IDs separados por coma (para la API)")
    parser.add_argument("--archivo-permisos", default=None, help="Ruta al Excel de permisos")
    parser.add_argument("--archivo-marcaciones", default=None, help="Ruta al Excel de marcaciones")
    args = parser.parse_args()

    start = datetime.strptime(args.fecha_inicio, "%Y-%m-%d").date()
    end = datetime.strptime(args.fecha_fin, "%Y-%m-%d").date()
    user_ids = [u.strip() for u in args.empleados.split(",") if u.strip()]

    paths = run(
        start_date=start,
        end_date=end,
        user_ids=user_ids,
        permisos_file=args.archivo_permisos,
        marcaciones_file=args.archivo_marcaciones,
    )
    print("\nArchivos generados:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
