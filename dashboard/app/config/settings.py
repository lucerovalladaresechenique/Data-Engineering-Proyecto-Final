"""
Configuración centralizada de la app (patrón Singleton).

Schema confirmado en la capa gold (star schema):

  dim_empleado          : empleado_id, empleado_codigo, empleado_nombre, area
  dim_turno             : turno_nombre, hora_inicio, hora_fin, es_nocturno
                           (sin FK directa a fact_asistencia_diaria; no se usa
                           por ahora — ver README si se agrega en el futuro)
  fact_asistencia_diaria: empleado_id, fecha, hora_entrada, hora_salida,
                           horas_trabajadas, horas_extra, horas_nocturnas,
                           tardanza_minutos, tipo_dia (Normal/Falta/Tardanza)
                           -> una fila por día esperado por empleado
  fact_ausentismo       : empleado_codigo, empleado_nombre, tipo_ausencia,
                           fecha_inicio, fecha_fin, dias_ausencia
                           -> se une a dim_empleado por empleado_codigo
                           (recuerda el mismatch documentado en dq_rules.md:
                           ~40% de match real entre sistemas)
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class AppSettings:
    # --- Recursos GCP (mismos del proyecto de asistencia) ---
    gcp_project: str = os.getenv("GCP_PROJECT", "proyecto-final-505619")
    gcs_bucket: str = os.getenv("GCS_BUCKET", "proyecto-final-505619-asistencia")
    bq_dataset: str = os.getenv("BQ_DATASET", "gold")

    # --- Nombres de tabla (confirmados) ---
    tabla_dim_empleado: str = os.getenv("TABLA_DIM_EMPLEADO", "dim_empleado")
    tabla_fact_asistencia: str = os.getenv(
        "TABLA_FACT_ASISTENCIA", "fact_asistencia_diaria"
    )
    tabla_fact_ausentismo: str = os.getenv(
        "TABLA_FACT_AUSENTISMO", "fact_ausentismo"
    )

    # --- Ruta local a Parquet (fallback / modo offline sin BigQuery) ---
    local_parquet_glob: str = os.getenv(
        "LOCAL_PARQUET_GLOB", "data/gold/fact_asistencia_diaria*.parquet"
    )
    local_parquet_ausentismo_glob: str = os.getenv(
        "LOCAL_PARQUET_AUSENTISMO_GLOB", "data/gold/fact_ausentismo*.parquet"
    )

    # --- Fuente de datos: "bigquery" o "parquet" ---
    data_source: str = os.getenv("DATA_SOURCE", "bigquery")

    # --- Cache ---
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))

    # --- Credenciales GCP (Application Default Credentials o key file) ---
    google_application_credentials: str = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )

    @property
    def fqn_dim_empleado(self) -> str:
        return f"{self.gcp_project}.{self.bq_dataset}.{self.tabla_dim_empleado}"

    @property
    def fqn_fact_asistencia(self) -> str:
        return f"{self.gcp_project}.{self.bq_dataset}.{self.tabla_fact_asistencia}"

    @property
    def fqn_fact_ausentismo(self) -> str:
        return f"{self.gcp_project}.{self.bq_dataset}.{self.tabla_fact_ausentismo}"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Punto único de acceso a la configuración (Singleton vía lru_cache)."""
    return AppSettings()
