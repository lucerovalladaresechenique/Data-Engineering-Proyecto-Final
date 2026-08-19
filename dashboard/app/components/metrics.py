"""
Componente de métricas: KPI cards de asistencia general.
"""

import streamlit as st

from app.services.attendance_data import AttendanceKPIs


def render_kpis(kpis: AttendanceKPIs) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Asistencia", f"{kpis.porcentaje_asistencia}%")
    col2.metric("Faltas", f"{kpis.porcentaje_faltas}%")
    col3.metric("Tardanzas", f"{kpis.porcentaje_tardanzas}%")
    col4.metric("Horas trabajadas (prom.)", f"{kpis.horas_trabajadas_promedio}h")
    col5.metric("Horas extra (total)", f"{kpis.horas_extra_total}h")

    st.caption(
        f"{kpis.total_empleados} empleados · {kpis.total_dias} días en el rango seleccionado"
    )
