"""
file_extractor.py — Extracción desde archivos Excel (RRHH)
=============================================================
Dos fuentes reales:
  - Historial de Solicitudes (permisos)  -> sheet "Permisos"
  - Marcaciones GeoVictoria (export)     -> sheet "Marcaciones"

Ambas llegan como .xlsx, con encabezados y formatos particulares del
export de GeoVictoria (ver docstrings de cada método).

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import re
from pathlib import Path

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

NAME_CODE_RE = re.compile(r"^(?P<nombre>.*?)\((?P<codigo>[^)]+)\)\s*$")
FECHA_RE = re.compile(r"^\w+\s+(\d{2}-\d{2}-\d{4})$")  # "Lun 01-06-2026" -> "01-06-2026"

PUNCH_SLOTS = [
    ("Entró 1", "Tipo 1", "Coordenadas 1", "entrada", 1),
    ("Salió 1", "Tipo 2", "Coordenadas 2", "salida", 2),
    ("Entró 2", "Tipo 3", "Coordenadas 3", "entrada", 3),
    ("Salió 2", "Tipo 4", "Coordenadas 4", "salida", 4),
]


class ExcelExtractor:
    """
    Lee los dos formatos Excel de RRHH usados como fuente en bronze.

    Ejemplo:
        extractor = ExcelExtractor()
        permisos_df = extractor.extract_permisos("HistorialdeSolicitudes.xlsx")
        marcas_df = extractor.extract_marcaciones("Marcaciones_GeoVictoria.xlsx")
    """

    # ──────────────────────────────────────────
    # Permisos
    # ──────────────────────────────────────────

    def extract_permisos(self, file_path: str | Path) -> pd.DataFrame:
        """
        Sheet "Permisos", encabezado real en la fila 3 (header=2).
        "Nombre" viene como "NOMBRE APELLIDO(código)" — se separa en dos campos.
        """
        file_path = Path(file_path)
        logger.info(f"Leyendo Permisos ← {file_path}")

        df = pd.read_excel(file_path, sheet_name="Permisos", header=2)
        df.columns = [c.strip() for c in df.columns]

        expected = ["Nombre", "Nombre Grupo", "Tipo Permiso", "Fecha de Solicitud", "Fecha Inicial", "Fecha Final", "Estado"]
        missing = [c for c in expected if c not in df.columns]
        if missing:
            raise ValueError(f"Faltan columnas en Permisos: {missing}. Encontradas: {list(df.columns)}")

        nombres_codigos = df["Nombre"].apply(self._split_nombre_codigo)
        df["empleado_nombre"] = [n for n, _ in nombres_codigos]
        df["empleado_codigo"] = [c for _, c in nombres_codigos]

        df["fecha_solicitud"] = pd.to_datetime(df["Fecha de Solicitud"], dayfirst=True, errors="coerce")
        df["fecha_inicio"] = pd.to_datetime(df["Fecha Inicial"], dayfirst=True, errors="coerce")
        df["fecha_fin"] = pd.to_datetime(df["Fecha Final"], dayfirst=True, errors="coerce")

        df = df.rename(columns={"Nombre Grupo": "nombre_grupo", "Tipo Permiso": "tipo_permiso", "Estado": "estado_solicitud"})
        df["source_file_name"] = file_path.name

        out = df[["empleado_nombre", "empleado_codigo", "nombre_grupo", "tipo_permiso",
                   "fecha_solicitud", "fecha_inicio", "fecha_fin", "estado_solicitud", "source_file_name"]]
        logger.info(f"✓ {len(out):,} permisos leídos")
        return out

    @staticmethod
    def _split_nombre_codigo(raw: str) -> tuple[str, str]:
        if not isinstance(raw, str):
            return None, None
        m = NAME_CODE_RE.match(raw.strip())
        if not m:
            return raw.strip(), None
        return m.group("nombre").strip(), m.group("codigo").strip()

    # ──────────────────────────────────────────
    # Marcaciones (export ancho)
    # ──────────────────────────────────────────

    def extract_marcaciones(self, file_path: str | Path) -> pd.DataFrame:
        """
        Sheet "Marcaciones": 1 fila = 1 empleado + 1 día, hasta 4 marcas en
        columnas anchas. Se aplana (melt) a 1 fila por marca individual.
        Tipo: A = app móvil (con GPS), M = manual, W = web.
        No incluye método biométrico (huella/rostro).
        """
        file_path = Path(file_path)
        logger.info(f"Leyendo Marcaciones ← {file_path}")

        df = pd.read_excel(file_path, sheet_name="Marcaciones", header=0)
        df.columns = [c.strip() for c in df.columns]

        required = ["Nombre", "Apellidos", "Identificador", "Grupo", "Fecha"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Faltan columnas en Marcaciones: {missing}. Encontradas: {list(df.columns)}")

        df["empleado_id"] = df["Identificador"].astype(str)
        df["empleado_nombre"] = df["Nombre"].astype(str) + " " + df["Apellidos"].astype(str)
        df["fecha"] = df["Fecha"].apply(self._parse_fecha)

        rows = []
        for _, row in df.iterrows():
            for hora_col, tipo_col, coord_col, tipo_marca, secuencia in PUNCH_SLOTS:
                hora = row.get(hora_col)
                if pd.isna(hora):
                    continue
                timestamp_marca = row["fecha"] + hora if pd.notna(row["fecha"]) else pd.NaT
                rows.append({
                    "empleado_id": row["empleado_id"],
                    "empleado_nombre": row["empleado_nombre"],
                    "grupo": row["Grupo"],
                    "fecha": row["fecha"],
                    "secuencia": secuencia,
                    "tipo_marca": tipo_marca,
                    "timestamp_marca": timestamp_marca,
                    "origen_marca": row.get(tipo_col),
                    "coordenadas": row.get(coord_col),
                })

        out = pd.DataFrame(rows)
        out["source_file_name"] = file_path.name
        logger.info(f"✓ {len(out):,} marcas aplanadas de {len(df):,} filas empleado/día")
        return out

    @staticmethod
    def _parse_fecha(raw: str):
        if not isinstance(raw, str):
            return pd.NaT
        m = FECHA_RE.match(raw.strip())
        if not m:
            return pd.NaT
        return pd.to_datetime(m.group(1), format="%d-%m-%Y", errors="coerce")
