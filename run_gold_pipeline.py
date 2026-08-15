"""
run_gold_pipeline.py — Punto de entrada CLI del pipeline Gold.

Requiere que ya se haya corrido run_pipeline.py para la misma fecha
(lee las tablas Silver desde OUTPUT_DIR/silver/.../ingestion_date=<fecha>/).

Uso:
    python run_gold_pipeline.py --fecha 2026-08-14
"""
import argparse
from datetime import datetime

from src.gold_pipeline import run_gold


def main():
    parser = argparse.ArgumentParser(description="Pipeline Gold de Control de Asistencia")
    parser.add_argument("--fecha", required=True, help="YYYY-MM-DD, misma fecha usada al correr run_pipeline.py")
    args = parser.parse_args()

    fecha = datetime.strptime(args.fecha, "%Y-%m-%d").date()
    paths = run_gold(ingestion_date=fecha)

    print("\nArchivos Gold generados:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()