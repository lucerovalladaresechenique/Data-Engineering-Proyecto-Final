"""
ver_parquet.py — Inspecciona un archivo Parquet del pipeline en la terminal.

Uso:
    python ver_parquet.py out/gold/fact_asistencia_diaria/ingestion_date=2026-06-01/data.parquet

Si no pasas ruta, usa una por defecto (ajústala abajo).
"""
import sys
import pandas as pd

RUTA_POR_DEFECTO = "out/gold/fact_asistencia_diaria/ingestion_date=2026-06-01/data.parquet"

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

ruta = sys.argv[1] if len(sys.argv) > 1 else RUTA_POR_DEFECTO
df = pd.read_parquet(ruta)

print(f"\nArchivo: {ruta}")
print(f"Filas: {len(df):,} | Columnas: {list(df.columns)}\n")
print(df.head(20).to_string())

# Descomenta para exportar a Excel y verlo con doble click:
df.to_excel("preview.xlsx", index=False)
print("\n✓ Exportado a preview.xlsx")