"""
Dashboard de Asistencia de Personal
Sesión 5 · Python Certified Data Engineer · BSG Institute

Lee las tablas gold (fact_asistencia_diaria, dim_empleado, fact_ausentismo)
del pipeline de asistencia y las muestra en un dashboard Streamlit: KPIs
generales, ranking de faltas, tendencia diaria/mensual y desglose de
ausentismo por tipo, con filtros de área y rango de fechas.
"""

import streamlit as st

from app.components.charts import (
    render_ausentismo_por_tipo,
    render_ranking_faltas,
    render_tendencia,
)
from app.components.metrics import render_kpis
from app.components.sidebar import render_sidebar
from app.config.settings import get_settings
from app.services.attendance_data import AttendanceDataError, AttendanceDataService


def main() -> None:
    st.set_page_config(
        page_title="Dashboard de Asistencia",
        page_icon="📊",
        layout="wide",
    )
    st.title("📊 Dashboard de Asistencia de Personal")

    settings = get_settings()
    service = AttendanceDataService(settings)

    config = render_sidebar(service)

    st.caption(
        f"Fuente: BigQuery · `{settings.fqn_fact_asistencia}`"
        if settings.data_source == "bigquery"
        else f"Fuente: Parquet local (`{settings.local_parquet_glob}`)"
    )

    try:
        kpis = service.get_kpis(config.fecha_inicio, config.fecha_fin, config.area)
        render_kpis(kpis)

        st.divider()

        col_left, col_right = st.columns(2)
        with col_left:
            ranking = service.get_ranking_faltas(
                config.fecha_inicio, config.fecha_fin, config.area
            )
            render_ranking_faltas(ranking)

        with col_right:
            tendencia = service.get_tendencia(
                config.fecha_inicio,
                config.fecha_fin,
                config.area,
                config.granularidad,
            )
            render_tendencia(tendencia, config.granularidad)

        st.divider()

        try:
            ausentismo = service.get_ausentismo_por_tipo(
                config.fecha_inicio, config.fecha_fin, config.area
            )
            render_ausentismo_por_tipo(ausentismo)
            st.caption(
                "⚠️ El cruce con fact_ausentismo usa empleado_codigo, que "
                "según dq_rules.md tiene ~40% de match real entre sistemas. "
                "Cifras referenciales."
            )
        except AttendanceDataError as exc:
            st.warning(f"No se pudo cargar el desglose de ausentismo: {exc}")

    except AttendanceDataError as exc:
        st.error(f"No se pudieron cargar los datos de asistencia: {exc}")
        st.info(
            "Verifica los nombres de tabla en `app/config/settings.py` "
            "y que tengas credenciales GCP configuradas "
            "(`GOOGLE_APPLICATION_CREDENTIALS`)."
        )


if __name__ == "__main__":
    main()
