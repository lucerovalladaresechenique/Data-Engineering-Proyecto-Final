"""
Tests básicos del AttendanceDataService usando datos Parquet locales
(sin necesidad de credenciales GCP), sobre el schema real de gold:
dim_empleado + fact_asistencia_diaria + fact_ausentismo.
"""

from datetime import date

import pandas as pd
import pytest

from app.config.settings import AppSettings
from app.services.attendance_data import AttendanceDataService


@pytest.fixture
def sample_dirs(tmp_path):
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()

    fact_asistencia = pd.DataFrame(
        {
            "empleado_id": ["E1", "E2", "E1", "E2"],
            "fecha": pd.to_datetime(
                ["2026-08-01", "2026-08-01", "2026-08-02", "2026-08-02"]
            ),
            "hora_entrada": ["08:00", None, None, "08:05"],
            "hora_salida": ["17:00", None, None, "17:00"],
            "horas_trabajadas": [8.0, 0.0, 0.0, 8.0],
            "horas_extra": [0.0, 0.0, 0.0, 0.5],
            "horas_nocturnas": [0.0, 0.0, 0.0, 0.0],
            "tardanza_minutos": [0, 0, 0, 5],
            "tipo_dia": ["Normal", "Falta", "Falta", "Tardanza"],
            "empleado_nombre": ["Ana", "Luis", "Ana", "Luis"],
            "area": ["Ventas", "TI", "Ventas", "TI"],
        }
    )
    fact_asistencia.to_parquet(gold_dir / "fact_asistencia_diaria_2026-08.parquet")

    fact_ausentismo = pd.DataFrame(
        {
            "empleado_codigo": ["C2"],
            "empleado_nombre": ["Luis"],
            "tipo_ausencia": ["Vacaciones"],
            "fecha_inicio": pd.to_datetime(["2026-08-01"]),
            "fecha_fin": pd.to_datetime(["2026-08-02"]),
            "dias_ausencia": [2],
            "area": ["TI"],
        }
    )
    fact_ausentismo.to_parquet(gold_dir / "fact_ausentismo_2026-08.parquet")

    return str(gold_dir)


@pytest.fixture
def service(sample_dirs):
    settings = AppSettings(
        data_source="parquet",
        local_parquet_glob=f"{sample_dirs}/fact_asistencia_diaria*.parquet",
        local_parquet_ausentismo_glob=f"{sample_dirs}/fact_ausentismo*.parquet",
    )
    return AttendanceDataService(settings)


def test_get_kpis_returns_expected_percentages(service):
    kpis = service.get_kpis(date(2026, 8, 1), date(2026, 8, 2))
    assert kpis.total_empleados == 2
    # normal + tardanza cuentan como asistencia: 2 de 4 filas
    assert kpis.porcentaje_asistencia == 50.0
    assert kpis.porcentaje_faltas == 50.0


def test_get_ranking_faltas_orders_by_count(service):
    ranking = service.get_ranking_faltas(date(2026, 8, 1), date(2026, 8, 2))
    assert len(ranking) >= 1
    assert ranking[0].total_faltas >= 1


def test_get_tendencia_diaria_has_one_row_per_day(service):
    tendencia = service.get_tendencia(
        date(2026, 8, 1), date(2026, 8, 2), granularidad="diaria"
    )
    assert len(tendencia) == 2
    assert tendencia[0].periodo == "2026-08-01"


def test_get_areas_lists_unique_areas(service):
    areas = service.get_areas()
    assert "Todas" in areas
    assert "Ventas" in areas
    assert "TI" in areas


def test_get_ausentismo_por_tipo(service):
    ausentismo = service.get_ausentismo_por_tipo(date(2026, 8, 1), date(2026, 8, 2))
    assert len(ausentismo) == 1
    assert ausentismo[0].tipo_ausencia == "Vacaciones"
    assert ausentismo[0].total_dias == 2
