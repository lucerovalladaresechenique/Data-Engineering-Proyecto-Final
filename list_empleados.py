"""
list_empleados.py — Extrae los IDs únicos de empleados desde el Excel de
Marcaciones y los guarda en empleados.txt, uno por línea.

Uso:
    python list_empleados.py data_samples/Marcaciones_GeoVictoria.xlsx
"""
import sys
import pandas as pd

archivo = sys.argv[1] if len(sys.argv) > 1 else "data_samples/Marcaciones_GeoVictoria.xlsx"

df = pd.read_excel(archivo, sheet_name="Marcaciones", usecols=["Identificador"])
ids = sorted(df["Identificador"].dropna().astype(str).unique())

with open("empleados.txt", "w") as f:
    f.write("\n".join(ids))

print(f"✓ {len(ids)} IDs únicos escritos en empleados.txt")