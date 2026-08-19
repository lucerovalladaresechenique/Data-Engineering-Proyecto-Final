"""
Componente de sidebar: filtros de fecha y área.
Contrato de datos explícito vía SidebarConfig (dataclass).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import streamlit as st

from app.services.attendance_data import AttendanceDataService


@dataclass(frozen=True)
class SidebarConfig:
    fecha_inicio: date
    fecha_fin: date
    area: str
    granularidad: str  # "diaria" | "mensual"


def render_sidebar(service: AttendanceDataService) -> SidebarConfig:
    st.sidebar.header("Filtros")

    hoy = date.today()
    rango_default = (hoy - timedelta(days=30), hoy)

    fecha_rango = st.sidebar.date_input(
        "Rango de fechas",
        value=rango_default,
        max_value=hoy,
    )
    if isinstance(fecha_rango, tuple) and len(fecha_rango) == 2:
        fecha_inicio, fecha_fin = fecha_rango
    else:
        fecha_inicio, fecha_fin = rango_default

    try:
        areas = service.get_areas()
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"No se pudieron cargar las áreas: {exc}")
        areas = ["Todas"]

    area = st.sidebar.selectbox("Área", options=areas, index=0)

    granularidad_label = st.sidebar.radio(
        "Tendencia", options=["Diaria", "Mensual"], horizontal=True
    )
    granularidad = "mensual" if granularidad_label == "Mensual" else "diaria"

    if st.sidebar.button("🔄 Limpiar caché"):
        for attr in (
            "get_areas",
            "get_kpis",
            "get_ranking_faltas",
            "get_tendencia",
            "get_ausentismo_por_tipo",
        ):
            getattr(service, attr).clear_cache()
        st.sidebar.success("Caché limpiado")

    return SidebarConfig(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        area=area,
        granularidad=granularidad,
    )
