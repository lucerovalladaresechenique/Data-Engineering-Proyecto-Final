"""
Componente de gráficos: ranking de faltas por empleado, tendencia
diaria/mensual de asistencia, y desglose de tipos de ausencia.
"""

import pandas as pd
import streamlit as st

from app.services.attendance_data import AusentismoTipoRow, RankingFaltasRow, TendenciaRow


def render_ranking_faltas(rows: list[RankingFaltasRow]) -> None:
    st.subheader("Ranking de faltas por empleado")

    if not rows:
        st.info("No hay faltas registradas en el rango/área seleccionados.")
        return

    df = pd.DataFrame(
        [
            {
                "Empleado": r.empleado_nombre,
                "Área": r.area,
                "Faltas": r.total_faltas,
            }
            for r in rows
        ]
    ).set_index("Empleado")

    st.bar_chart(df["Faltas"])
    with st.expander("Ver tabla detallada"):
        st.dataframe(df, use_container_width=True)


def render_tendencia(rows: list[TendenciaRow], granularidad: str) -> None:
    label = "mensual" if granularidad == "mensual" else "diaria"
    st.subheader(f"Tendencia {label} de asistencia")

    if not rows:
        st.info("No hay datos suficientes para mostrar la tendencia.")
        return

    df = pd.DataFrame(
        [
            {
                "Periodo": r.periodo,
                "% Asistencia": r.porcentaje_asistencia,
                "Faltas": r.total_faltas,
            }
            for r in rows
        ]
    ).set_index("Periodo")

    st.line_chart(df["% Asistencia"])
    with st.expander("Ver faltas por periodo"):
        st.bar_chart(df["Faltas"])


def render_ausentismo_por_tipo(rows: list[AusentismoTipoRow]) -> None:
    st.subheader("Ausentismo por tipo de permiso")

    if not rows:
        st.info("No hay registros de ausentismo en el rango/área seleccionados.")
        return

    df = pd.DataFrame(
        [
            {
                "Tipo de ausencia": r.tipo_ausencia,
                "Días totales": r.total_dias,
                "Eventos": r.total_eventos,
            }
            for r in rows
        ]
    ).set_index("Tipo de ausencia")

    st.bar_chart(df["Días totales"])
    with st.expander("Ver tabla detallada"):
        st.dataframe(df, use_container_width=True)
