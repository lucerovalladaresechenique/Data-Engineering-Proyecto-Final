"""
Service Layer: AttendanceDataService

Desacopla la UI (Streamlit) de la fuente de datos (BigQuery gold / Parquet
local). Lee el star schema real de tu pipeline:

  fact_asistencia_diaria (grano: día × empleado, incluye ausentes con
  hora_entrada/hora_salida en null) JOIN dim_empleado (nombre, área).
  El estado (Normal/Falta/Tardanza) ya viene calculado en `tipo_dia`.

  fact_ausentismo se usa aparte para el desglose de tipos de permiso
  (vacaciones, licencias, etc. — 20 tipos distintos), unido a
  dim_empleado por empleado_codigo.
"""

from dataclasses import dataclass
from datetime import date
from glob import glob
from typing import Optional

import pandas as pd
from google.api_core import exceptions as google_exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config.settings import AppSettings, get_settings
from app.services.cache import cached


# --------------------------------------------------------------------------
# Contratos de datos (dataclasses explícitos)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AttendanceKPIs:
    total_empleados: int
    total_dias: int
    porcentaje_asistencia: float
    porcentaje_faltas: float
    porcentaje_tardanzas: float
    horas_trabajadas_promedio: float
    horas_extra_total: float


@dataclass(frozen=True)
class RankingFaltasRow:
    empleado_id: str
    empleado_nombre: str
    area: str
    total_faltas: int


@dataclass(frozen=True)
class TendenciaRow:
    periodo: str  # fecha (diaria) o "YYYY-MM" (mensual)
    porcentaje_asistencia: float
    total_faltas: int


@dataclass(frozen=True)
class AusentismoTipoRow:
    tipo_ausencia: str
    total_eventos: int
    total_dias: int


# --------------------------------------------------------------------------
# Excepciones propias del servicio
# --------------------------------------------------------------------------

class AttendanceDataError(RuntimeError):
    """Error al obtener datos de asistencia desde BigQuery o Parquet."""


# --------------------------------------------------------------------------
# Service Layer
# --------------------------------------------------------------------------

class AttendanceDataService:
    def __init__(self, settings: Optional[AppSettings] = None):
        self.settings = settings or get_settings()
        self._bq_client = None  # lazy init

    # ---- infra ----

    def _get_bq_client(self):
        if self._bq_client is None:
            from google.cloud import bigquery  # import perezoso

            self._bq_client = bigquery.Client(project=self.settings.gcp_project)
        return self._bq_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (
                google_exceptions.ServerError,
                google_exceptions.TooManyRequests,
                google_exceptions.ServiceUnavailable,
            )
        ),
        reraise=True,
    )
    def _run_query(self, sql: str) -> pd.DataFrame:
        client = self._get_bq_client()
        return client.query(sql).to_dataframe()

    def _load_parquet(self, glob_pattern: str) -> pd.DataFrame:
        files = sorted(glob(glob_pattern))
        if not files:
            raise AttendanceDataError(
                f"No se encontraron archivos Parquet en '{glob_pattern}'"
            )
        latest = max(files, key=lambda f: f)
        return pd.read_parquet(latest)

    # ---- carga de fact_asistencia_diaria + dim_empleado ----

    def _load_asistencia_df(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
    ) -> pd.DataFrame:
        s = self.settings

        if s.data_source == "bigquery":
            where_clauses = []
            if fecha_inicio:
                where_clauses.append(f"f.fecha >= '{fecha_inicio.isoformat()}'")
            if fecha_fin:
                where_clauses.append(f"f.fecha <= '{fecha_fin.isoformat()}'")
            if area and area != "Todas":
                area_escaped = area.replace("'", "''")
                where_clauses.append(f"e.area = '{area_escaped}'")

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            sql = f"""
                SELECT
                    f.fecha,
                    f.empleado_id,
                    e.empleado_nombre,
                    e.area,
                    f.tipo_dia            AS estado,
                    f.horas_trabajadas,
                    f.horas_extra,
                    f.horas_nocturnas,
                    f.tardanza_minutos
                FROM `{s.fqn_fact_asistencia}` f
                JOIN `{s.fqn_dim_empleado}` e
                    ON CAST(f.empleado_id AS STRING) = CAST(e.empleado_id AS STRING)
                {where_sql}
            """
            try:
                df = self._run_query(sql)
            except Exception as exc:  # noqa: BLE001
                raise AttendanceDataError(
                    f"Error consultando BigQuery ({s.fqn_fact_asistencia}): {exc}"
                ) from exc
        else:
            fact = self._load_parquet(s.local_parquet_glob)

            if "empleado_nombre" not in fact.columns or "area" not in fact.columns:
                emp_glob = s.local_parquet_glob.replace(
                    "fact_asistencia_diaria", "dim_empleado"
                )
                emp = self._load_parquet(emp_glob)
                df = fact.merge(emp, on="empleado_id", how="left")
            else:
                df = fact

            df = df.rename(columns={"tipo_dia": "estado"})
            if fecha_inicio:
                df = df[df["fecha"] >= pd.Timestamp(fecha_inicio)]
            if fecha_fin:
                df = df[df["fecha"] <= pd.Timestamp(fecha_fin)]
            if area and area != "Todas":
                df = df[df["area"] == area]

        if df.empty:
            return df

        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    # ---- carga de fact_ausentismo + dim_empleado ----

    def _load_ausentismo_df(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
    ) -> pd.DataFrame:
        s = self.settings

        if s.data_source == "bigquery":
            where_clauses = []
            if fecha_inicio:
                where_clauses.append(f"a.fecha_inicio <= '{fecha_fin.isoformat() if fecha_fin else fecha_inicio.isoformat()}'")
                where_clauses.append(f"a.fecha_fin >= '{fecha_inicio.isoformat()}'")
            if area and area != "Todas":
                area_escaped = area.replace("'", "''")
                where_clauses.append(f"e.area = '{area_escaped}'")

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            # NOTA: join por empleado_codigo — recuerda el mismatch documentado
            # en dq_rules.md (~40% de match real entre sistemas).
            sql = f"""
                SELECT
                    a.tipo_ausencia,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.dias_ausencia,
                    e.area
                FROM `{s.fqn_fact_ausentismo}` a
                LEFT JOIN `{s.fqn_dim_empleado}` e
                    ON CAST(a.empleado_codigo AS STRING) = CAST(e.empleado_codigo AS STRING)
                {where_sql}
            """
            try:
                df = self._run_query(sql)
            except Exception as exc:  # noqa: BLE001
                raise AttendanceDataError(
                    f"Error consultando BigQuery ({s.fqn_fact_ausentismo}): {exc}"
                ) from exc
        else:
            df = self._load_parquet(s.local_parquet_ausentismo_glob)
            if fecha_inicio and fecha_fin:
                df = df[
                    (pd.to_datetime(df["fecha_inicio"]) <= pd.Timestamp(fecha_fin))
                    & (pd.to_datetime(df["fecha_fin"]) >= pd.Timestamp(fecha_inicio))
                ]
            if area and area != "Todas" and "area" in df.columns:
                df = df[df["area"] == area]

        return df

    # ---- API pública (usada por components/) ----

    @cached(ttl_seconds=get_settings().cache_ttl_seconds)
    def get_areas(self) -> list[str]:
        df = self._load_asistencia_df()
        if df.empty:
            return ["Todas"]
        return ["Todas"] + sorted(df["area"].dropna().unique().tolist())

    @cached(ttl_seconds=get_settings().cache_ttl_seconds)
    def get_kpis(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
    ) -> AttendanceKPIs:
        df = self._load_asistencia_df(fecha_inicio, fecha_fin, area)
        if df.empty:
            return AttendanceKPIs(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

        total = len(df)
        estado_lower = df["estado"].astype(str).str.lower()
        normales = estado_lower.eq("normal").sum()
        faltas = estado_lower.eq("falta").sum()
        tardanzas = estado_lower.eq("tardanza").sum()

        return AttendanceKPIs(
            total_empleados=df["empleado_id"].nunique(),
            total_dias=df["fecha"].nunique(),
            porcentaje_asistencia=round(100 * (normales + tardanzas) / total, 2) if total else 0.0,
            porcentaje_faltas=round(100 * faltas / total, 2) if total else 0.0,
            porcentaje_tardanzas=round(100 * tardanzas / total, 2) if total else 0.0,
            horas_trabajadas_promedio=round(df["horas_trabajadas"].mean(), 2)
            if "horas_trabajadas" in df
            else 0.0,
            horas_extra_total=round(df["horas_extra"].sum(), 2)
            if "horas_extra" in df
            else 0.0,
        )

    @cached(ttl_seconds=get_settings().cache_ttl_seconds)
    def get_ranking_faltas(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
        top_n: int = 15,
    ) -> list[RankingFaltasRow]:
        df = self._load_asistencia_df(fecha_inicio, fecha_fin, area)
        if df.empty:
            return []

        faltas_df = df[df["estado"].astype(str).str.lower() == "falta"]
        if faltas_df.empty:
            return []

        ranking = (
            faltas_df.groupby(["empleado_id", "empleado_nombre", "area"])
            .size()
            .reset_index(name="total_faltas")
            .sort_values("total_faltas", ascending=False)
            .head(top_n)
        )

        return [
            RankingFaltasRow(
                empleado_id=str(row.empleado_id),
                empleado_nombre=str(row.empleado_nombre),
                area=str(row.area),
                total_faltas=int(row.total_faltas),
            )
            for row in ranking.itertuples()
        ]

    @cached(ttl_seconds=get_settings().cache_ttl_seconds)
    def get_tendencia(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
        granularidad: str = "diaria",  # "diaria" | "mensual"
    ) -> list[TendenciaRow]:
        df = self._load_asistencia_df(fecha_inicio, fecha_fin, area)
        if df.empty:
            return []

        if granularidad == "mensual":
            df["periodo"] = df["fecha"].dt.strftime("%Y-%m")
        else:
            df["periodo"] = df["fecha"].dt.strftime("%Y-%m-%d")

        estado_lower = df["estado"].astype(str).str.lower()
        df["_es_asistencia"] = estado_lower.isin(["normal", "tardanza"])
        df["_es_falta"] = estado_lower.eq("falta")

        grouped = (
            df.groupby("periodo")
            .agg(
                total=("estado", "size"),
                asistencias=("_es_asistencia", "sum"),
                faltas=("_es_falta", "sum"),
            )
            .reset_index()
            .sort_values("periodo")
        )
        grouped["porcentaje_asistencia"] = round(
            100 * grouped["asistencias"] / grouped["total"], 2
        )

        return [
            TendenciaRow(
                periodo=str(row.periodo),
                porcentaje_asistencia=float(row.porcentaje_asistencia),
                total_faltas=int(row.faltas),
            )
            for row in grouped.itertuples()
        ]

    @cached(ttl_seconds=get_settings().cache_ttl_seconds)
    def get_ausentismo_por_tipo(
        self,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        area: Optional[str] = None,
    ) -> list[AusentismoTipoRow]:
        """
        Desglose de permisos/ausencias por tipo (vacaciones, licencias, etc.)
        desde fact_ausentismo. Join por empleado_codigo — recuerda que este
        cruce es imperfecto (~40% match), documentado en dq_rules.md.
        """
        df = self._load_ausentismo_df(fecha_inicio, fecha_fin, area)
        if df.empty:
            return []

        grouped = (
            df.groupby("tipo_ausencia")
            .agg(total_eventos=("tipo_ausencia", "size"), total_dias=("dias_ausencia", "sum"))
            .reset_index()
            .sort_values("total_dias", ascending=False)
        )

        return [
            AusentismoTipoRow(
                tipo_ausencia=str(row.tipo_ausencia),
                total_eventos=int(row.total_eventos),
                total_dias=int(row.total_dias),
            )
            for row in grouped.itertuples()
        ]
