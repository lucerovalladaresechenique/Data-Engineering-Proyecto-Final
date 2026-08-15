"""
transformer.py — Transformaciones del pipeline de Control de Asistencia
==========================================================================
Aplana la respuesta anidada de AttendanceBook, limpia los Excel de RRHH,
aplica el mapeo de tipos de permiso y corrige el cruce de medianoche en
turnos nocturnos (ver architecture/dq_rules.md).

Principios: inmutabilidad, trazabilidad, funciones puras + orquestador.

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

from datetime import datetime, timezone

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

DATE_FMT = "%Y%m%d%H%M%S"

# Mapeo propuesto de los 20 "Tipo Permiso" reales -> 4 categorías de negocio.
# Ajustar libremente según criterio de RRHH.
TIPO_PERMISO_MAP: dict[str, str] = {
    "Descansos Vacacionales": "vacaciones",
    "Vacaciones": "vacaciones",
    "Suspensión laboral": "suspension",
    "Capacitación": "capacitacion",
    "Descanso Médico": "licencia",
    "Descanso médico: Enferm.": "licencia",
    "Descanso médico: Acc.Trab": "licencia",
    "Licencia sin Goce de Haber": "licencia",
    "Licencia con Goce Haber": "licencia",
    "Licencia por Colaborador de mes": "licencia",
    "Licencia Sindical": "licencia",
    "Licencia por Paternidad": "licencia",
    "Licencia por Fallecimiento": "licencia",
    "Permiso con goce de haber": "licencia",
    "Permisos sin Goce de Haber": "licencia",
    "Permiso: Cuidarte es primero": "licencia",
    "Permiso: Tu día, tu tiempo": "licencia",
    "Subsidio por Enfermedad": "licencia",
    "Subsidio por Accidente": "licencia",
    "Subsidio Maternidad": "licencia",
}

# Solo estos estados de solicitud justifican una falta.
ESTADOS_APROBADOS = {"Solicitud aprobada"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class AttendanceTransformer:
    """
    Orquesta las transformaciones Bronze -> Silver del proyecto de asistencia.

    Ejemplo:
        transformer = AttendanceTransformer(pipeline_version="1.0.0")
        result = transformer.transform(raw_data)
        result["silver_marcaciones"]  # DataFrame
    """

    def __init__(self, pipeline_version: str = "1.0.0"):
        self.pipeline_version = pipeline_version

    # ──────────────────────────────────────────
    # AttendanceBook (API) -> marcas / turnos
    # ──────────────────────────────────────────

    def transform_attendance_book(self, users_raw: list[dict]) -> dict[str, pd.DataFrame]:
        """
        Aplana Users -> PlannedInterval -> {Punches, Shifts} de AttendanceBook
        en dos DataFrames: marcas_api y turnos_api.
        """
        logger.info(f"Transformando AttendanceBook: {len(users_raw)} colaboradores...")
        type_map = {"Ingreso": "entrada", "Salida": "salida"}

        punch_rows, shift_rows = [], []
        for user in users_raw:
            empleado_id = str(user.get("Identifier"))
            for interval in user.get("PlannedInterval", []):
                fecha = interval.get("Date")

                for punch in interval.get("Punches", []):
                    punch_rows.append({
                        "empleado_id": empleado_id,
                        "timestamp_marca": punch.get("Date"),
                        "tipo_marca": type_map.get(punch.get("Type"), punch.get("Type")),
                        "origen_marca": punch.get("Origin"),
                        "raw_payload": str(punch),
                    })

                for shift in interval.get("Shifts", []):
                    shift_rows.append({
                        "empleado_id": empleado_id,
                        "fecha": fecha,
                        "turno_nombre": shift.get("ShiftDisplay"),
                        "hora_inicio_programada": shift.get("StartTime"),
                        "hora_fin_programada": shift.get("ExitTime"),
                        "break_minutos": shift.get("BreakMinutes"),
                        "break_inicio": shift.get("BreakStart"),
                        "break_fin": shift.get("BreakEnd"),
                    })

        marcas_df = pd.DataFrame(punch_rows)
        if not marcas_df.empty:
            marcas_df["timestamp_marca"] = pd.to_datetime(marcas_df["timestamp_marca"], format=DATE_FMT, errors="coerce")

        turnos_df = pd.DataFrame(shift_rows)
        if not turnos_df.empty:
            turnos_df["fecha"] = pd.to_datetime(turnos_df["fecha"], format=DATE_FMT, errors="coerce")

        logger.info(f"✓ {len(marcas_df):,} marcas y {len(turnos_df):,} turnos aplanados desde la API")
        return {"marcas_api": marcas_df, "turnos_api": turnos_df}

    # ──────────────────────────────────────────
    # Marcaciones Excel — corrige cruce de medianoche
    # ──────────────────────────────────────────

    def transform_marcaciones_excel(self, marcas_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Corrige el cruce de medianoche: si la marca de salida (secuencia par)
        queda con timestamp anterior a la entrada previa del mismo empleado+
        fecha, se le suma 1 día (ver architecture/dq_rules.md).
        """
        logger.info(f"Transformando marcaciones Excel: {len(marcas_raw):,} marcas...")
        df = marcas_raw.sort_values(["empleado_id", "fecha", "secuencia"]).copy()

        df["timestamp_marca_corregido"] = df["timestamp_marca"]
        prev_ts = None
        prev_key = None
        corregidas = 0

        for idx, row in df.iterrows():
            key = (row["empleado_id"], row["fecha"])
            if row["tipo_marca"] == "salida" and prev_key == key and pd.notna(row["timestamp_marca"]) and pd.notna(prev_ts):
                if row["timestamp_marca"] < prev_ts:
                    df.at[idx, "timestamp_marca_corregido"] = row["timestamp_marca"] + pd.Timedelta(days=1)
                    corregidas += 1
            prev_ts = df.at[idx, "timestamp_marca_corregido"]
            prev_key = key

        if corregidas:
            logger.warning(f"  ↳ {corregidas} marcas de salida corregidas por cruce de medianoche")

        df["_processed_at"] = _now_utc()
        df["_pipeline_version"] = self.pipeline_version
        return df

    # ──────────────────────────────────────────
    # Permisos — aplica mapeo de 20 -> 4 categorías
    # ──────────────────────────────────────────

    def transform_permisos(self, permisos_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Filtra solo solicitudes aprobadas y clasifica tipo_permiso original
        en tipo_ausencia (vacaciones|licencia|suspension|capacitacion) usando
        TIPO_PERMISO_MAP. Tipos no mapeados quedan como "sin_clasificar" y se
        loguean para revisión.
        """
        logger.info(f"Transformando permisos: {len(permisos_raw):,} solicitudes...")
        df = permisos_raw.copy()

        before = len(df)
        df = df[df["estado_solicitud"].isin(ESTADOS_APROBADOS)]
        logger.info(f"  ↳ {before - len(df):,} solicitudes descartadas (no aprobadas)")

        # Normaliza espacios extra (el Excel real trae valores como "Descanso Médico "
        # con espacio final) antes de mapear, para no perder coincidencias por whitespace.
        tipo_normalizado = df["tipo_permiso"].str.strip()
        df["tipo_ausencia"] = tipo_normalizado.map(TIPO_PERMISO_MAP).fillna("sin_clasificar")
        sin_clasificar = df[df["tipo_ausencia"] == "sin_clasificar"]["tipo_permiso"].unique()
        if len(sin_clasificar):
            logger.warning(f"  ↳ tipos de permiso sin mapeo: {list(sin_clasificar)}")

        df["_processed_at"] = _now_utc()
        df["_pipeline_version"] = self.pipeline_version
        logger.info(f"✓ Permisos clasificados: {len(df):,}")
        return df

    # ──────────────────────────────────────────
    # Orquestador
    # ──────────────────────────────────────────

    def transform(self, raw_data: dict) -> dict:
        """
        Args:
            raw_data: dict con keys opcionales:
                'attendance_book_users' -> list[dict] (respuesta cruda de la API)
                'permisos_excel'        -> DataFrame crudo (ExcelExtractor.extract_permisos)
                'marcaciones_excel'     -> DataFrame crudo (ExcelExtractor.extract_marcaciones)

        Returns:
            dict con DataFrames listos para Silver + 'stats'.
        """
        logger.info("=== Iniciando transformaciones ===")
        result = {}

        if "attendance_book_users" in raw_data:
            api_out = self.transform_attendance_book(raw_data["attendance_book_users"])
            result["silver_marcaciones_api"] = api_out["marcas_api"]
            result["silver_turnos"] = api_out["turnos_api"]

        if "marcaciones_excel" in raw_data:
            result["silver_marcaciones_excel"] = self.transform_marcaciones_excel(raw_data["marcaciones_excel"])

        if "permisos_excel" in raw_data:
            result["silver_ausencias"] = self.transform_permisos(raw_data["permisos_excel"])

        stats = {name: len(df) for name, df in result.items() if isinstance(df, pd.DataFrame)}
        logger.info(f"=== Transformación completa === {stats}")
        result["stats"] = stats
        return result
