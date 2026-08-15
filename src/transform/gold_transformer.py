"""
gold_transformer.py — Construcción de la capa Gold (Serving)
=================================================================
Cruza silver_marcaciones_excel + silver_turnos + silver_ausencias para
producir las tablas de negocio: fact_asistencia_diaria, fact_ausentismo,
dim_empleado, dim_turno.

⚠️ LIMITACIÓN CONOCIDA: silver_ausencias (viene del Excel de permisos) usa
   nombre+código como identificador; silver_marcaciones_excel/silver_turnos
   (vienen de GeoVictoria) usan el Identificador numérico. No hay llave común
   directa. Este módulo cruza por nombre normalizado (mayúsculas, sin tildes,
   espacios colapsados) como solución provisional — es sensible a diferencias
   de orden de apellidos o tildes. La solución correcta es traer el catálogo
   real de empleados vía el método User/List de la API (requiere OAuth 1.0,
   pendiente de implementar) para tener un cruce por Identifier confiable.

Regla de horas nocturnas: ventana 22:00–06:00 (jornada nocturna según
legislación laboral peruana general). Ajustar NIGHT_START/NIGHT_END si aplica
otra normativa.

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import unicodedata
from datetime import time, timedelta

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

NIGHT_START = time(22, 0)  # 22:00
NIGHT_END = time(6, 0)     # 06:00 del día siguiente


def _normalize_name(name: str) -> str:
    """'FERNANDO AGÜERO ESTRADA' -> 'FERNANDO AGUERO ESTRADA' (sin tildes, upper, sin dobles espacios)."""
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def _night_overlap_hours(start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Horas del intervalo [start, end) que caen dentro de la ventana nocturna 22:00–06:00."""
    if pd.isna(start) or pd.isna(end) or end <= start:
        return 0.0

    total_night = timedelta()
    cursor = start
    while cursor < end:
        day_end = pd.Timestamp.combine(cursor.date(), time(23, 59, 59, 999999))
        segment_end = min(end, day_end + timedelta(microseconds=1))

        night_start_today = pd.Timestamp.combine(cursor.date(), NIGHT_START)
        night_end_tomorrow = pd.Timestamp.combine(cursor.date() + timedelta(days=1), NIGHT_END)

        overlap_start = max(cursor, night_start_today)
        overlap_end = min(segment_end, night_end_tomorrow)
        if overlap_end > overlap_start:
            total_night += (overlap_end - overlap_start)

        # también cubre el tramo 00:00–06:00 del mismo día (madrugada)
        morning_end_today = pd.Timestamp.combine(cursor.date(), NIGHT_END)
        overlap_start2 = max(cursor, pd.Timestamp.combine(cursor.date(), time(0, 0)))
        overlap_end2 = min(segment_end, morning_end_today)
        if overlap_end2 > overlap_start2:
            total_night += (overlap_end2 - overlap_start2)

        cursor = segment_end

    return round(total_night.total_seconds() / 3600, 2)


class GoldTransformer:
    """
    Construye las tablas Gold a partir de las tablas Silver ya generadas.

    Ejemplo:
        gt = GoldTransformer()
        gold = gt.build(
            marcaciones_df=silver_marcaciones_excel,
            turnos_df=silver_turnos,
            ausencias_df=silver_ausencias,
        )
        gold["fact_asistencia_diaria"]
    """

    # ──────────────────────────────────────────
    # dim_empleado / dim_turno
    # ──────────────────────────────────────────

    def build_dim_empleado(self, marcaciones_df: pd.DataFrame, ausencias_df: pd.DataFrame) -> pd.DataFrame:
        """
        Combina los empleados vistos en marcaciones (con empleado_id numérico)
        y en ausencias (con empleado_codigo/RUT) usando el nombre normalizado
        como llave de cruce best-effort.
        """
        logger.info("Construyendo dim_empleado...")

        marc = marcaciones_df[["empleado_id", "empleado_nombre"]].drop_duplicates() if not marcaciones_df.empty else pd.DataFrame(columns=["empleado_id", "empleado_nombre"])
        marc["nombre_normalizado"] = marc["empleado_nombre"].apply(_normalize_name)

        aus = ausencias_df[["empleado_codigo", "empleado_nombre", "nombre_grupo"]].drop_duplicates() if not ausencias_df.empty else pd.DataFrame(columns=["empleado_codigo", "empleado_nombre", "nombre_grupo"])
        aus["nombre_normalizado"] = aus["empleado_nombre"].apply(_normalize_name)

        dim = marc.merge(
            aus[["nombre_normalizado", "empleado_codigo", "nombre_grupo", "empleado_nombre"]],
            on="nombre_normalizado", how="outer", suffixes=("", "_permisos"),
        )
        dim["empleado_nombre"] = dim["empleado_nombre"].fillna(dim["empleado_nombre_permisos"])

        dim = dim.rename(columns={"nombre_grupo": "area"})[
            ["empleado_id", "empleado_codigo", "empleado_nombre", "area"]
        ].drop_duplicates()

        logger.info(f"✓ dim_empleado: {len(dim):,} empleados ({dim['empleado_id'].notna().sum()} con ID de marcaciones, {dim['empleado_codigo'].notna().sum()} con código de permisos)")
        return dim

    def build_dim_turno(self, turnos_df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Construyendo dim_turno...")
        if turnos_df.empty:
            return pd.DataFrame(columns=["turno_nombre", "hora_inicio", "hora_fin", "es_nocturno"])

        dim = turnos_df[["turno_nombre", "hora_inicio_programada", "hora_fin_programada"]].drop_duplicates()
        dim = dim.rename(columns={"hora_inicio_programada": "hora_inicio", "hora_fin_programada": "hora_fin"})
        dim["es_nocturno"] = dim["hora_inicio"] > dim["hora_fin"]  # cruza medianoche
        logger.info(f"✓ dim_turno: {len(dim):,} turnos distintos")
        return dim

    @staticmethod
    def _parse_hhmm(fecha: pd.Timestamp, hhmm: str) -> pd.Timestamp | None:
        """Combina una fecha con una hora 'HH:MM' (formato StartTime/ExitTime de la API) en un timestamp."""
        if pd.isna(fecha) or not isinstance(hhmm, str) or ":" not in hhmm:
            return None
        try:
            h, m = hhmm.strip().split(":")[:2]
            return pd.Timestamp.combine(fecha.date() if hasattr(fecha, "date") else fecha, time(int(h), int(m)))
        except (ValueError, AttributeError):
            return None

    # ──────────────────────────────────────────
    # fact_asistencia_diaria
    # ──────────────────────────────────────────

    def build_fact_asistencia_diaria(
        self, marcaciones_df: pd.DataFrame, turnos_df: pd.DataFrame, ausencias_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Grano: 1 fila por empleado_id + fecha.
        - horas_trabajadas: suma de intervalos (entrada->salida) del día; el
          tiempo entre "salida 1" y "entrada 2" (colación) queda excluido
          automáticamente al sumar solo los intervalos entrada->salida.
        - horas_nocturnas: horas de esos intervalos dentro de 22:00–06:00.
        - horas_extra: max(0, horas_trabajadas - horas_turno_programado).
        - tardanza_minutos: minutos entre hora_inicio_programada y la primera
          entrada real (solo si hay turno para ese día).
        - tipo_dia: 'falta' si no hay marcas y no hay ausencia aprobada que
          cubra la fecha; 'ausencia_justificada' si sí la cubre; 'normal' en
          cualquier otro caso.
        """
        logger.info("Construyendo fact_asistencia_diaria...")

        rows = []
        marc = marcaciones_df.dropna(subset=["timestamp_marca_corregido"]).copy() if not marcaciones_df.empty else pd.DataFrame()
        if not marc.empty:
            grouped = marc.sort_values(["empleado_id", "fecha", "secuencia"]).groupby(["empleado_id", "fecha"])
        else:
            grouped = []

        # empleados vistos en ausencias, para poder marcar 'ausencia_justificada'
        # en fechas donde NO hay marcaciones (falta física con permiso aprobado)
        ausencias_lookup = ausencias_df.copy() if not ausencias_df.empty else pd.DataFrame(columns=["empleado_nombre", "fecha_inicio", "fecha_fin"])
        if not ausencias_lookup.empty:
            ausencias_lookup["nombre_normalizado"] = ausencias_lookup["empleado_nombre"].apply(_normalize_name)

        for (empleado_id, fecha), grupo in grouped:
            marcas = grupo.sort_values("secuencia")
            entradas = marcas[marcas["tipo_marca"] == "entrada"]["timestamp_marca_corregido"].tolist()
            salidas = marcas[marcas["tipo_marca"] == "salida"]["timestamp_marca_corregido"].tolist()

            horas_trabajadas = 0.0
            horas_nocturnas = 0.0
            for entrada, salida in zip(entradas, salidas):
                if pd.notna(entrada) and pd.notna(salida) and salida > entrada:
                    horas_trabajadas += (salida - entrada).total_seconds() / 3600
                    horas_nocturnas += _night_overlap_hours(entrada, salida)

            turno_dia = turnos_df[(turnos_df["empleado_id"] == empleado_id) & (turnos_df["fecha"] == fecha)] if not turnos_df.empty else pd.DataFrame()
            horas_turno = None
            tardanza_minutos = None
            if not turno_dia.empty:
                t = turno_dia.iloc[0]
                inicio_prog = self._parse_hhmm(fecha, t.get("hora_inicio_programada"))
                fin_prog = self._parse_hhmm(fecha, t.get("hora_fin_programada"))
                if inicio_prog is not None and fin_prog is not None:
                    if fin_prog <= inicio_prog:  # turno cruza medianoche
                        fin_prog += timedelta(days=1)
                    horas_turno = round((fin_prog - inicio_prog).total_seconds() / 3600, 2)

                if entradas and inicio_prog is not None:
                    primera_entrada = min(entradas)
                    diff_min = (primera_entrada - inicio_prog).total_seconds() / 60
                    tardanza_minutos = round(diff_min) if diff_min > 0 else 0

            horas_extra = round(max(0.0, horas_trabajadas - horas_turno), 2) if horas_turno else None

            rows.append({
                "empleado_id": empleado_id,
                "fecha": fecha,
                "hora_entrada": min(entradas) if entradas else pd.NaT,
                "hora_salida": max(salidas) if salidas else pd.NaT,
                "horas_trabajadas": round(horas_trabajadas, 2),
                "horas_extra": horas_extra,
                "horas_nocturnas": round(horas_nocturnas, 2),
                "tardanza_minutos": tardanza_minutos,
                "tipo_dia": "normal",
            })

        fact = pd.DataFrame(rows)

        # Días sin ninguna marca: clasificar como falta o ausencia_justificada
        fact = self._flag_faltas_y_ausencias(fact, marcaciones_df, ausencias_lookup)

        logger.info(f"✓ fact_asistencia_diaria: {len(fact):,} filas (empleado x día)")
        return fact

    def _flag_faltas_y_ausencias(self, fact: pd.DataFrame, marcaciones_df: pd.DataFrame, ausencias_lookup: pd.DataFrame) -> pd.DataFrame:
        """
        Genera filas adicionales para (empleado, fecha) dentro del rango de
        datos donde el empleado NO tiene marcas — se clasifican como
        'ausencia_justificada' si hay un permiso aprobado que cubre la fecha,
        o 'falta' en caso contrario.
        """
        if marcaciones_df.empty:
            return fact

        empleados = marcaciones_df[["empleado_id", "empleado_nombre"]].drop_duplicates()
        rango_fechas = pd.date_range(marcaciones_df["fecha"].min(), marcaciones_df["fecha"].max(), freq="D")

        dias_esperados = empleados.assign(key=1).merge(pd.DataFrame({"fecha": rango_fechas, "key": 1}), on="key").drop(columns="key")
        dias_con_marca = fact[["empleado_id", "fecha"]].drop_duplicates()
        dias_con_marca["_tiene_marca"] = True

        faltantes = dias_esperados.merge(dias_con_marca, on=["empleado_id", "fecha"], how="left")
        faltantes = faltantes[faltantes["_tiene_marca"].isna()].copy()

        if faltantes.empty:
            return fact

        faltantes["nombre_normalizado"] = faltantes["empleado_nombre"].apply(_normalize_name)
        faltantes["tipo_dia"] = "falta"

        if not ausencias_lookup.empty:
            for idx, row in faltantes.iterrows():
                cubierto = ausencias_lookup[
                    (ausencias_lookup["nombre_normalizado"] == row["nombre_normalizado"])
                    & (ausencias_lookup["fecha_inicio"] <= row["fecha"])
                    & (ausencias_lookup["fecha_fin"] >= row["fecha"])
                ]
                if not cubierto.empty:
                    faltantes.at[idx, "tipo_dia"] = "ausencia_justificada"

        faltantes["horas_trabajadas"] = 0.0
        faltantes["horas_extra"] = 0.0
        faltantes["horas_nocturnas"] = 0.0
        faltantes["hora_entrada"] = pd.NaT
        faltantes["hora_salida"] = pd.NaT
        faltantes["tardanza_minutos"] = None

        cols = ["empleado_id", "fecha", "hora_entrada", "hora_salida", "horas_trabajadas", "horas_extra", "horas_nocturnas", "tardanza_minutos", "tipo_dia"]
        return pd.concat([fact, faltantes[cols]], ignore_index=True)

    # ──────────────────────────────────────────
    # fact_ausentismo
    # ──────────────────────────────────────────

    def build_fact_ausentismo(self, ausencias_df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Construyendo fact_ausentismo...")
        if ausencias_df.empty:
            return pd.DataFrame(columns=["empleado_codigo", "empleado_nombre", "tipo_ausencia", "fecha_inicio", "fecha_fin", "dias_ausencia"])

        df = ausencias_df.copy()
        df["dias_ausencia"] = (df["fecha_fin"].dt.normalize() - df["fecha_inicio"].dt.normalize()).dt.days + 1

        out = df[["empleado_codigo", "empleado_nombre", "tipo_ausencia", "fecha_inicio", "fecha_fin", "dias_ausencia"]]
        logger.info(f"✓ fact_ausentismo: {len(out):,} periodos de ausencia")
        return out

    # ──────────────────────────────────────────
    # Orquestador
    # ──────────────────────────────────────────

    def build(self, marcaciones_df: pd.DataFrame, turnos_df: pd.DataFrame, ausencias_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        logger.info("=== Construyendo capa Gold ===")
        gold = {
            "dim_empleado": self.build_dim_empleado(marcaciones_df, ausencias_df),
            "dim_turno": self.build_dim_turno(turnos_df),
            "fact_asistencia_diaria": self.build_fact_asistencia_diaria(marcaciones_df, turnos_df, ausencias_df),
            "fact_ausentismo": self.build_fact_ausentismo(ausencias_df),
        }
        stats = {name: len(df) for name, df in gold.items()}
        logger.info(f"=== Gold completo === {stats}")
        gold["stats"] = stats
        return gold
